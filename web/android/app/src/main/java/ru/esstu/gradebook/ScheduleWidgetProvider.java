package ru.esstu.gradebook;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.util.Calendar;
import java.util.List;
import java.util.Locale;

/**
 * Виджет расписания на рабочем столе.
 *
 * ━━ ЧТО ПОКАЗЫВАЕТ ━━
 * Расписание ПОСЛЕДНЕГО вошедшего аккаунта: у студента — его группы, у преподавателя —
 * его пары (там, где у пары вместо преподавателя стоит группа). Кто именно — решает
 * веб-слой при сохранении снимка, нативная часть про роли ничего не знает и знать не
 * должна: это ровно та развилка, которая уже разобрана на сервере по роли токена.
 *
 * ━━ ТРИ РАЗМЕРА ━━
 * Размер определяется не «типом виджета», а фактическими габаритами ячейки — человек
 * растягивает виджет как хочет, и три отдельных виджета в списке добавления
 * (маленький/средний/большой) заставляли бы его удалять и добавлять заново вместо
 * того, чтобы просто потянуть за угол.
 *   • узкий (≈2×2) — «что сейчас/дальше», одна пара крупно;
 *   • средний (≈4×2) — до трёх ближайших пар;
 *   • большой (≈4×4+) — весь день с преподавателем и аудиторией.
 *
 * ━━ ЧАСТОТА ОБНОВЛЕНИЯ ━━
 * `updatePeriodMillis` в системе не бывает чаще 30 минут — это ограничение Android, а
 * не наш выбор, и на подсветку «идёт сейчас» оно даёт погрешность до получаса. Точный
 * будильник ради этого не заводим: на Android 12+ он требует отдельного разрешения
 * (SCHEDULE_EXACT_ALARM), а просить у человека такое право ради подсветки строки —
 * несоразмерно. Дополнительно виджет перерисовывается при смене даты/времени и каждый
 * раз, когда приложение кладёт свежий снимок.
 */
public class ScheduleWidgetProvider extends AppWidgetProvider {

    /** Границы размеров в dp — по габаритам ячейки, а не по числу «клеток». */
    private static final int NARROW_MAX_DP = 180;
    /** Ниже этой высоты шапка сжимается в одну строку, а подвал прячется (см. buildList). */
    private static final int SHORT_MAX_DP = 160;

    // Высоты элементов в dp — те же числа, что в widget_schedule_list.xml и
    // widget_schedule_row.xml. Из них считается, сколько строк реально влезет.
    //
    // ⚠️ Раньше здесь стояли константы «3 строки на средний, 7 на большой», и это
    // был реальный дефект, пойманный предпросмотром разметки: на 4×2 (высота ячейки
    // около 110-120dp) три строки не помещались — третья уезжала под подвал и
    // обрезалась на середине. Считать по фактической высоте надёжнее: человек тянет
    // виджет за угол на любой размер, и подобрать константу «на все случаи» нельзя.
    private static final int PADDING_DP = 24;          //padding 12 сверху + 12 снизу
    private static final int HEADER_TALL_DP = 34;      //день + подпись под ним
    private static final int HEADER_SHORT_DP = 18;     //только день
    private static final int ROWS_MARGIN_DP = 8;
    private static final int FOOTER_DP = 17;           //текст + marginTop
    private static final int ROW_TALL_DP = 38;         //номер над временем + «тип · кто»
    private static final int ROW_SHORT_DP = 26;        //компактная строка в одну линию
    private static final int ROW_GAP_DP = 5;

    /** Разумный потолок: больше восьми пар в дне у колледжа не бывает. */
    private static final int ROWS_MAX = 8;

    @Override
    public void onUpdate(Context ctx, AppWidgetManager mgr, int[] ids) {
        for (int id : ids) {
            render(ctx, mgr, id);
        }
    }

    @Override
    public void onAppWidgetOptionsChanged(Context ctx, AppWidgetManager mgr, int id,
                                          Bundle newOptions) {
        //Виджет растянули/сжали — раскладка обязана смениться сразу, иначе крупный
        //виджет останется с содержимым мелкого и будет выглядеть сломанным.
        render(ctx, mgr, id);
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        super.onReceive(ctx, intent);
        String action = intent != null ? intent.getAction() : null;
        if (Intent.ACTION_DATE_CHANGED.equals(action)
                || Intent.ACTION_TIME_CHANGED.equals(action)
                || Intent.ACTION_TIMEZONE_CHANGED.equals(action)) {
            //Наступили новые сутки — «сегодня» стало другим днём недели, а на границе
            //года меняется ещё и чётность. Без этого виджет до получаса показывал бы
            //вчерашний день, что хуже пустого: цифры настоящие, но не про тот день.
            refreshAll(ctx);
        }
    }

    /** Перерисовать все размещённые виджеты. Зовётся и из моста, когда пришли данные. */
    static void refreshAll(Context ctx) {
        AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
        ComponentName cn = new ComponentName(ctx, ScheduleWidgetProvider.class);
        int[] ids = mgr.getAppWidgetIds(cn);
        if (ids == null) {
            return;
        }
        for (int id : ids) {
            render(ctx, mgr, id);
        }
    }

    private static void render(Context ctx, AppWidgetManager mgr, int id) {
        Bundle opts = mgr.getAppWidgetOptions(id);
        int wDp = opts != null ? opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 0) : 0;
        int hDp = opts != null ? opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 0) : 0;

        JSONObject snap = ScheduleWidgetData.snapshot(ctx);
        Calendar now = Calendar.getInstance();

        RemoteViews rv;
        if (wDp > 0 && wDp < NARROW_MAX_DP) {
            rv = buildSmall(ctx, snap, now);
        } else {
            //Средний (низкий) размер отдаёт место строкам: подпись под днём и подвал
            //уходят, шапка сжимается в одну строку. На большом всё возвращается.
            boolean detailed = !(hDp > 0 && hDp < SHORT_MAX_DP);
            rv = buildList(ctx, snap, now, rowsThatFit(hDp, detailed), detailed);
        }

        //Тап по виджету открывает приложение. Отдельного deep-link на страницу
        //расписания не делаем: OTA подменяет веб-бандл, и маршрут SPA может уехать —
        //ссылка бы протухла молча. Открыть приложение надёжно всегда.
        Intent open = new Intent(ctx, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        rv.setOnClickPendingIntent(R.id.widget_root,
                PendingIntent.getActivity(ctx, 0, open, flags));

        mgr.updateAppWidget(id, rv);
    }

    // МАЛЫЙ ────────────────────────────────────────────────────────────────────────
    private static RemoteViews buildSmall(Context ctx, JSONObject snap, Calendar now) {
        RemoteViews rv = new RemoteViews(ctx.getPackageName(), R.layout.widget_schedule_small);
        if (snap == null) {
            rv.setTextViewText(R.id.w_title, "GradeBookAI");
            rv.setTextViewText(R.id.w_week, "");
            rv.setTextViewText(R.id.w_state, "");
            rv.setTextViewText(R.id.w_time, "—");
            rv.setTextViewText(R.id.w_subject, "Откройте приложение, чтобы загрузить расписание");
            rv.setTextViewText(R.id.w_foot, "");
            return rv;
        }

        rv.setTextViewText(R.id.w_title, snap.optString("title", ""));
        rv.setTextViewText(R.id.w_week, weekLabel(snap, now, false));

        ScheduleWidgetData.Day day = ScheduleWidgetData.nextDayWithPairs(snap, now);
        if (day == null || day.pairs.isEmpty()) {
            rv.setTextViewText(R.id.w_state, "");
            rv.setTextViewText(R.id.w_time, "Пар нет");
            rv.setTextViewText(R.id.w_subject, "На ближайшую неделю занятий не найдено");
            rv.setTextViewText(R.id.w_foot, updatedLabel(snap));
            return rv;
        }

        int nowMin = ScheduleWidgetData.minutesOfDay(now);
        ScheduleWidgetData.Pair chosen = null;
        String state;
        int left = 0;

        if (day.offset == 0) {
            //Сегодняшний день: сначала ищем идущую пару, потом ближайшую следующую.
            for (ScheduleWidgetData.Pair p : day.pairs) {
                if (p.startMin >= 0 && p.endMin >= 0 && nowMin >= p.startMin && nowMin < p.endMin) {
                    chosen = p;
                    break;
                }
            }
            state = chosen != null ? "Сейчас" : "Дальше";
            if (chosen == null) {
                for (ScheduleWidgetData.Pair p : day.pairs) {
                    if (p.startMin < 0 || p.startMin > nowMin) {
                        chosen = p;
                        break;
                    }
                }
            }
            if (chosen == null) {
                //Все пары дня уже закончились — честнее сказать это, чем показать
                //первую пару дня так, будто она ещё впереди.
                rv.setTextViewText(R.id.w_state, "На сегодня всё");
                rv.setTextViewText(R.id.w_time, "Пар больше нет");
                rv.setTextViewText(R.id.w_subject, "");
                rv.setTextViewText(R.id.w_foot, updatedLabel(snap));
                return rv;
            }
            for (ScheduleWidgetData.Pair p : day.pairs) {
                if (p.startMin < 0 || p.endMin < 0 || nowMin < p.endMin) {
                    left++;
                }
            }
            left = Math.max(0, left - 1);
        } else {
            chosen = day.pairs.get(0);
            state = day.offset == 1 ? "Завтра" : ScheduleWidgetData.weekdayFull(day.date);
            left = day.pairs.size() - 1;
        }

        rv.setTextViewText(R.id.w_state, state);
        rv.setTextViewText(R.id.w_time, chosen.time.isEmpty()
                ? (chosen.no + " пара") : chosen.time.replace('-', '–'));
        rv.setTextViewText(R.id.w_subject, chosen.subject.isEmpty() ? "—" : chosen.subject);

        StringBuilder foot = new StringBuilder();
        if (!chosen.room.isEmpty()) {
            foot.append("ауд. ").append(chosen.room);
        }
        if (left > 0) {
            if (foot.length() > 0) {
                foot.append(" · ");
            }
            foot.append("ещё ").append(left);
        }
        if (foot.length() == 0) {
            foot.append(updatedLabel(snap));
        }
        rv.setTextViewText(R.id.w_foot, foot.toString());
        return rv;
    }

    // СРЕДНИЙ И БОЛЬШОЙ ───────────────────────────────────────────────────────────
    /**
     * Сколько строк пар реально помещается в виджет высотой hDp.
     *
     * Считаем, а не подбираем константу: виджет растягивается произвольно, и «три
     * строки» верны ровно для одного размера. Строка, не влезшая целиком, обрезается
     * системой на середине текста — выглядит как поломка, поэтому лучше показать на
     * одну меньше и честно дописать в подвал «ещё N пар».
     *
     * hDp == 0 (лаунчер не сообщил габариты — бывает на первом размещении) — берём
     * скромные две строки: недобор места виден сразу, а обрезка — не всегда.
     */
    static int rowsThatFit(int hDp, boolean detailed) {
        if (hDp <= 0) {
            return 2;
        }
        int header = detailed ? HEADER_TALL_DP : HEADER_SHORT_DP;
        int footer = detailed ? FOOTER_DP : 0;
        int avail = hDp - PADDING_DP - header - ROWS_MARGIN_DP - footer;
        int rowH = (detailed ? ROW_TALL_DP : ROW_SHORT_DP) + ROW_GAP_DP;
        int fit = avail / rowH;
        return Math.max(1, Math.min(ROWS_MAX, fit));
    }

    private static RemoteViews buildList(Context ctx, JSONObject snap, Calendar now,
                                         int maxRows, boolean detailed) {
        RemoteViews rv = new RemoteViews(ctx.getPackageName(), R.layout.widget_schedule_list);
        rv.removeAllViews(R.id.w_rows);
        //На низком виджете подпись под днём и подвал съедали ровно ту высоту, которой
        //не хватало второй строке пары. Дата и «обновлено» там менее ценны, чем сама
        //пара, поэтому прячем их, а не ужимаем шрифт до нечитаемого.
        if (!detailed) {
            rv.setViewVisibility(R.id.w_title, android.view.View.GONE);
            rv.setViewVisibility(R.id.w_foot, android.view.View.GONE);
        }

        if (snap == null) {
            rv.setTextViewText(R.id.w_day, "GradeBookAI");
            rv.setTextViewText(R.id.w_title, "Расписание");
            rv.setTextViewText(R.id.w_week, "");
            rv.setViewVisibility(R.id.w_rows, android.view.View.GONE);
            rv.setViewVisibility(R.id.w_empty, android.view.View.VISIBLE);
            rv.setTextViewText(R.id.w_empty, "Откройте приложение —\nрасписание загрузится само");
            rv.setTextViewText(R.id.w_foot, "");
            return rv;
        }

        ScheduleWidgetData.Day day = ScheduleWidgetData.nextDayWithPairs(snap, now);
        Calendar shown = day != null ? day.date : now;

        String when;
        if (day == null || day.offset == 0) {
            when = "Сегодня, " + ScheduleWidgetData.weekdayFull(shown);
        } else if (day.offset == 1) {
            when = "Завтра, " + ScheduleWidgetData.weekdayFull(shown);
        } else {
            String full = ScheduleWidgetData.weekdayFull(shown);
            when = Character.toUpperCase(full.charAt(0)) + full.substring(1);
        }
        rv.setTextViewText(R.id.w_day, when);

        String title = snap.optString("title", "");
        String sub = ScheduleWidgetData.dateHuman(shown);
        rv.setTextViewText(R.id.w_title, title.isEmpty() ? sub : (title + " · " + sub));
        rv.setTextViewText(R.id.w_week, weekLabel(snap, shown, true));

        if (day == null || day.pairs.isEmpty()) {
            rv.setViewVisibility(R.id.w_rows, android.view.View.GONE);
            rv.setViewVisibility(R.id.w_empty, android.view.View.VISIBLE);
            rv.setTextViewText(R.id.w_empty, "Пар нет");
            rv.setTextViewText(R.id.w_foot, updatedLabel(snap));
            return rv;
        }

        rv.setViewVisibility(R.id.w_empty, android.view.View.GONE);
        rv.setViewVisibility(R.id.w_rows, android.view.View.VISIBLE);

        int nowMin = ScheduleWidgetData.minutesOfDay(now);
        List<ScheduleWidgetData.Pair> all = day.pairs;

        //РАЗНЫЕ размеры отвечают на РАЗНЫЕ вопросы, и отбор строк из этого и следует.
        //  • низкий (4×2) — «что дальше»: две-три строки, и тратить их на уже
        //    закончившуюся пару нельзя;
        //  • большой — «как выглядит мой день»: там прошедшие пары нужны, они дают
        //    опору («сейчас третья из пяти»), а без них виджет ещё и полупустой к
        //    вечеру. Прошедшие рисуем приглушённо — понятно, что они позади.
        //Ничего из этого не относится к ЗАВТРАШНЕМУ дню: там прошедших нет вовсе.
        int firstIdx = 0;
        if (day.offset == 0 && !detailed) {
            for (int i = 0; i < all.size(); i++) {
                ScheduleWidgetData.Pair p = all.get(i);
                if (p.endMin < 0 || nowMin < p.endMin) {
                    firstIdx = i;
                    break;
                }
                firstIdx = i + 1;
            }
        }
        //Если места меньше, чем пар, на большом виджете сдвигаем окно к текущей паре:
        //показать первые четыре пары дня в шесть вечера — то же самое, что показать
        //вчерашний день.
        if (detailed && day.offset == 0 && all.size() > maxRows) {
            int current = 0;
            for (int i = 0; i < all.size(); i++) {
                ScheduleWidgetData.Pair p = all.get(i);
                if (p.endMin < 0 || nowMin < p.endMin) {
                    current = i;
                    break;
                }
                current = i + 1;
            }
            firstIdx = Math.max(0, Math.min(current, all.size() - maxRows));
        }

        int shownCount = 0;
        for (int i = firstIdx; i < all.size() && shownCount < maxRows; i++, shownCount++) {
            ScheduleWidgetData.Pair p = all.get(i);
            boolean isNow = day.offset == 0 && p.startMin >= 0 && p.endMin >= 0
                    && nowMin >= p.startMin && nowMin < p.endMin;
            boolean isPast = day.offset == 0 && p.endMin >= 0 && nowMin >= p.endMin;
            rv.addView(R.id.w_rows, row(ctx, p, isNow, isPast, detailed, shownCount > 0));
        }

        int rest = all.size() - firstIdx - shownCount;
        StringBuilder foot = new StringBuilder();
        if (rest > 0) {
            foot.append("ещё ").append(rest).append(pairWord(rest));
            foot.append(" · ");
        }
        foot.append(updatedLabel(snap));
        rv.setTextViewText(R.id.w_foot, foot.toString());
        return rv;
    }

    private static RemoteViews row(Context ctx, ScheduleWidgetData.Pair p, boolean isNow,
                                   boolean isPast, boolean detailed, boolean withTopGap) {
        //Две разметки строки, а не одна с прячущимися частями: у полной строки номер
        //пары стоит НАД временем, и высоту ниже ~37dp она не берёт при любом скрытии.
        //На низком виджете это давало ровно одну строку — см. rowsThatFit.
        int layout = detailed ? R.layout.widget_schedule_row
                              : R.layout.widget_schedule_row_compact;
        RemoteViews rv = new RemoteViews(ctx.getPackageName(), layout);
        rv.setInt(R.id.row_root, "setBackgroundResource",
                isNow ? R.drawable.widget_row_bg_now : R.drawable.widget_row_bg);

        //Показываем только начало пары: конец занимает столько же места, а нужен реже.
        String start = p.time;
        int dash = indexOfDash(start);
        if (dash > 0) {
            start = start.substring(0, dash).trim();
        }
        rv.setTextViewText(R.id.row_time, start);
        rv.setTextViewText(R.id.row_subject, p.subject.isEmpty() ? "—" : p.subject);

        if (detailed) {
            rv.setTextViewText(R.id.row_pair, isNow ? "идёт" : (p.no + " пара"));
            if (isNow) {
                rv.setTextColor(R.id.row_pair, ctx.getResources().getColor(R.color.gb_widget_accent));
            }
            StringBuilder meta = new StringBuilder();
            if (!p.kind.isEmpty()) {
                meta.append(p.kind);
            }
            if (!p.who.isEmpty()) {
                if (meta.length() > 0) {
                    meta.append(" · ");
                }
                meta.append(p.who);
            }
            if (meta.length() == 0) {
                rv.setViewVisibility(R.id.row_meta, android.view.View.GONE);
            } else {
                rv.setTextViewText(R.id.row_meta, meta.toString());
            }
        } else if (isNow) {
            //В компактной строке подписи «идёт» нет — её роль играет цвет времени
            //плюс левая полоса подложки (та видна и при дальтонизме).
            rv.setTextColor(R.id.row_time, ctx.getResources().getColor(R.color.gb_widget_accent));
        }

        if (p.room.isEmpty()) {
            rv.setViewVisibility(R.id.row_room, android.view.View.GONE);
        } else {
            rv.setTextViewText(R.id.row_room, p.room);
        }

        //Прошедшая пара — приглушённая, но НЕ скрытая: она держит контекст («сейчас
        //третья из пяти»). Гасим цветом, а не прозрачностью: setAlpha у RemoteViews
        //работает не на всех лаунчерах, а цвет — везде одинаково.
        if (isPast && !isNow) {
            int muted = ctx.getResources().getColor(R.color.gb_widget_past);
            rv.setTextColor(R.id.row_time, muted);
            rv.setTextColor(R.id.row_subject, muted);
            rv.setTextColor(R.id.row_room, muted);
        }

        //Отступ между строками — через padding самой строки: RemoteViews не умеет
        //задавать layout_margin у добавленной вьюхи.
        if (withTopGap) {
            int side = dp(ctx, 8);
            int base = detailed ? 5 : 4;
            rv.setViewPadding(R.id.row_root, side, dp(ctx, base + ROW_GAP_DP), side, dp(ctx, base));
        }
        return rv;
    }

    // МЕЛОЧИ ──────────────────────────────────────────────────────────────────────
    private static int indexOfDash(String s) {
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '-' || c == '–' || c == '—') {
                return i;
            }
        }
        return -1;
    }

    private static int dp(Context ctx, int value) {
        return Math.round(value * ctx.getResources().getDisplayMetrics().density);
    }

    private static String pairWord(int n) {
        int n100 = n % 100, n10 = n % 10;
        if (n100 >= 11 && n100 <= 14) {
            return " пар";
        }
        if (n10 == 1) {
            return " пара";
        }
        if (n10 >= 2 && n10 <= 4) {
            return " пары";
        }
        return " пар";
    }

    /**
     * «I неделя» / «II».
     *
     * Чётность считается на ДАТУ ПОКАЗЫВАЕМОГО ДНЯ, а не на сегодня: спрошенный в
     * субботу понедельник — это уже следующая неделя с другой чётностью. Та же
     * оговорка стоит и в серверной части расписания, ошибиться здесь легко.
     * У сессионных категорий (заочные) чётности нет вовсе — плашку прячем.
     */
    private static String weekLabel(JSONObject snap, Calendar cal, boolean withWord) {
        if ("dated".equals(snap.optString("kind"))) {
            return "";
        }
        int parity = ScheduleWidgetData.weekParity(cal);
        String roman = parity == 2 ? "II" : "I";
        return withWord ? roman + " неделя" : roman;
    }

    private static String updatedLabel(JSONObject snap) {
        long ts = snap.optLong("saved_at", 0L);
        if (ts <= 0) {
            return "";
        }
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis(ts);
        Calendar now = Calendar.getInstance();
        boolean sameDay = c.get(Calendar.YEAR) == now.get(Calendar.YEAR)
                && c.get(Calendar.DAY_OF_YEAR) == now.get(Calendar.DAY_OF_YEAR);
        if (sameDay) {
            return String.format(Locale.US, "обновлено %02d:%02d",
                    c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE));
        }
        return "обновлено " + ScheduleWidgetData.dateHuman(c);
    }
}
