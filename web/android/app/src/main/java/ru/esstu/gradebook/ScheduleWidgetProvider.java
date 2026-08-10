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

    // ⚠️ Констант высот строк здесь БОЛЬШЕ НЕТ, и это осознанно.
    //
    // Сначала стояли «3 строки на средний, 7 на большой» — предпросмотр разметки поймал
    // реальный дефект: на 4×2 три строки не помещались, третья обрезалась на середине
    // текста. Тогда число строк начали СЧИТАТЬ по фактической высоте ячейки. Но как
    // только шрифты выросли до читаемых с вытянутой руки, посчитанное честно число
    // оказалось равно полутора — и любой подсчёт стал бессмысленным: показывать одну
    // пару в широком виджете незачем.
    //
    // Ответ не в арифметике, а в прокрутке: список отдаёт коллекция (ListView +
    // ScheduleWidgetService), сколько влезло — столько видно, остальное человек
    // долистывает. Размер ячейки теперь решает только ДВА вопроса: узкий это виджет
    // (одна пара крупно) и показывать ли уже прошедшие пары.

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
        boolean dayChanged = Intent.ACTION_DATE_CHANGED.equals(action)
                || Intent.ACTION_TIME_CHANGED.equals(action)
                || Intent.ACTION_TIMEZONE_CHANGED.equals(action);
        if (dayChanged) {
            //Наступили новые сутки — «сегодня» стало другим днём недели, а на границе
            //года меняется ещё и чётность. Без этого виджет до получаса показывал бы
            //вчерашний день, что хуже пустого: цифры настоящие, но не про тот день.
            refreshAll(ctx);
        }
        if (dayChanged || AppWidgetManager.ACTION_APPWIDGET_UPDATE.equals(action)) {
            maybeFetchFresh(ctx);
        }
    }

    /**
     * Сходить за свежим расписанием, если пора (см. ScheduleWidgetRefresh).
     *
     * ⚠️ `goAsync()` обязателен. Сеть на главном потоке запрещена системой
     * (NetworkOnMainThreadException), а просто запущенный поток не спасает: как только
     * onReceive возвращает управление, процесс становится кандидатом на убийство, и
     * запрос обрывается на середине — незаметно и невоспроизводимо. `goAsync` продлевает
     * жизнь приёмнику ровно до `finish()`; наши таймауты (6 с соединение, 8 с чтение)
     * заведомо укладываются в отпущенное системой окно.
     *
     * Рисуем из кэша мы в любом случае РАНЬШЕ (super.onReceive выше), поэтому сеть здесь
     * никогда не задерживает появление виджета на экране.
     */
    private void maybeFetchFresh(Context ctx) {
        final PendingResult pending = goAsync();
        final Context app = ctx.getApplicationContext();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (ScheduleWidgetRefresh.refreshNow(app)) {
                        refreshAll(app);      //снимок реально сменился — перерисовать
                    }
                } catch (Throwable ignored) {
                    //Виджет — дополнение: любая его беда не имеет права уронить процесс.
                } finally {
                    pending.finish();
                }
            }
        }, "gb-widget-refresh").start();
    }

    /**
     * Все три класса-приёмника, под которыми виджет может быть размещён.
     *
     * ⚠️ В списке добавления теперь ТРИ пункта — 2×2, 4×2 и 4×4 (прямая просьба: одного
     * пункта, который «можно растянуть», человеку недостаточно, он хочет выбрать сразу).
     * Классы отличаются ТОЛЬКО стартовым размером и картинкой предпросмотра в своём
     * `appwidget-provider`; вся логика общая и живёт здесь. Растягивание при этом никуда
     * не делось: раскладку по-прежнему выбирает фактический размер ячейки, поэтому
     * поставленный «4×4» после сжатия до 2×2 честно станет маленьким.
     */
    static final Class<?>[] PROVIDERS = {
            ScheduleWidgetProvider.class,
            ScheduleWidgetSizes.Small.class,
            ScheduleWidgetSizes.Medium.class,
            ScheduleWidgetSizes.Large.class,
    };

    /** Перерисовать все размещённые виджеты. Зовётся и из моста, когда пришли данные. */
    static void refreshAll(Context ctx) {
        AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
        for (Class<?> cls : PROVIDERS) {
            int[] ids = mgr.getAppWidgetIds(new ComponentName(ctx, cls));
            if (ids == null) {
                continue;
            }
            for (int id : ids) {
                //Сначала сообщаем КОЛЛЕКЦИИ, что данные сменились (иначе список
                //перерисуется старым содержимым — RemoteViewsFactory кэшируется
                //системой), и только потом перерисовываем сам виджет.
                mgr.notifyAppWidgetViewDataChanged(id, R.id.w_rows);
                render(ctx, mgr, id);
            }
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
            //Низкий виджет отвечает на вопрос «что дальше» — прошедшие пары в нём не
            //показываем, места мало. Большой отвечает на «как выглядит мой день»: там
            //прошедшие нужны как опора («сейчас третья из пяти») и рисуются приглушённо.
            //Число строк БОЛЬШЕ НЕ СЧИТАЕМ: список прокручивается, сколько влезло —
            //столько видно, остальное человек долистает.
            boolean tall = !(hDp > 0 && hDp < SHORT_MAX_DP);
            rv = buildList(ctx, snap, now, id, tall);
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
                //
                //⚠️ В КРУПНУЮ строку идёт КОРОТКОЕ слово. Здесь стояло «Пар больше
                //нет» — четырнадцать знаков при 17sp жирным это около 126dp, а внутри
                //ячейки 2×2 остаётся примерно 86dp: строка обрезалась в «Пар больш…».
                //Пояснение перенесено в блок предмета — он при пустом дне всё равно
                //пустовал (12sp, три строки, места с запасом), и виджет заодно
                //перестал выглядеть наполовину незаполненным.
                rv.setTextViewText(R.id.w_state, "На сегодня всё");
                rv.setTextViewText(R.id.w_time, "Пар нет");
                rv.setTextViewText(R.id.w_subject, "Занятий сегодня больше нет");
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

        //ПЕРЕРЫВ. Если пара уже закончилась, а следующая скоро — вместо безликого
        //«Дальше» показываем, СКОЛЬКО ЖДАТЬ: «через 15 мин». Именно это человек и хочет
        //знать, глянув на телефон между парами, — время начала он потом ещё считает в
        //уме, а минуты до начала не требуют никакого счёта.
        //
        //Порог в полтора часа не случайный: за ним «через 200 минут» уже не помогает,
        //а мешает — там полезнее обычное время начала. Ноль минут не пишем никогда
        //(«через 0 мин» читается как ошибка): с этого момента и до звонка говорим
        //«вот-вот».
        if (day.offset == 0 && !"Сейчас".equals(state)
                && chosen.startMin >= 0 && chosen.startMin > nowMin) {
            int wait = chosen.startMin - nowMin;
            if (wait <= 90) {
                state = wait < 1 ? "Вот-вот" : ("Через " + wait + " " + minuteWord(wait));
            }
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

    /** «минуту» / «минуты» / «минут» — иначе «через 21 минут» выглядит как опечатка. */
    private static String minuteWord(int n) {
        int n100 = n % 100, n10 = n % 10;
        if (n100 >= 11 && n100 <= 14) {
            return "минут";
        }
        if (n10 == 1) {
            return "минуту";
        }
        if (n10 >= 2 && n10 <= 4) {
            return "минуты";
        }
        return "минут";
    }

    // СРЕДНИЙ И БОЛЬШОЙ ───────────────────────────────────────────────────────────
    /**
     * Шапка + ПРОКРУЧИВАЕМЫЙ список пар.
     *
     * ⚠️ Раньше здесь считалось, СКОЛЬКО строк влезет (`rowsThatFit`), и лишние просто
     * не показывались. С крупными читаемыми шрифтами это перестало работать: в низкую
     * ячейку влезает полторы пары, и «показать меньше» — не ответ. Теперь строки отдаёт
     * коллекция (ListView + ScheduleWidgetService), и то, что не поместилось,
     * ПРОКРУЧИВАЕТСЯ. Подсчёт строк удалён вместе с константами высот — он врал бы.
     *
     * ⚠️ `setRemoteAdapter` обязателен ДО `updateAppWidget`, а `notifyAppWidgetViewDataChanged`
     * — при каждом обновлении данных (см. refreshAll): фабрика кэшируется системой, и без
     * уведомления список остался бы вчерашним, хотя шапка обновилась бы. Это классическая
     * ловушка коллекционных виджетов: «шапка новая, список старый».
     */
    private static RemoteViews buildList(Context ctx, JSONObject snap, Calendar now,
                                         int widgetId, boolean tall) {
        RemoteViews rv = new RemoteViews(ctx.getPackageName(), R.layout.widget_schedule_list);

        //🔥 НА НИЗКОМ ВИДЖЕТЕ ПОДПИСЬ ПОД ДНЁМ И ПОДВАЛ ПРЯЧЕМ — иначе не остаётся места
        //НИ ОДНОЙ строке пары. Поймано предпросмотром разметки: с крупными шрифтами
        //строка занимает ~52dp, а на ячейке 4×2 (высота ~130dp) шапка с подписью и
        //подвал съедали ~75dp, и список оказывался пустым. Пустой виджет неотличим от
        //сломанного, поэтому дата и «обновлено» уступают место самой паре: они здесь
        //менее ценны, а ужимать шрифт до нечитаемого — значит вернуть ровно ту проблему,
        //ради которой шрифты и увеличивали.
        if (!tall) {
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
            rv.setViewVisibility(R.id.w_foot, android.view.View.GONE);
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
        rv.setTextViewText(R.id.w_foot, updatedLabel(snap));

        if (day == null || day.pairs.isEmpty()) {
            rv.setViewVisibility(R.id.w_rows, android.view.View.GONE);
            rv.setViewVisibility(R.id.w_empty, android.view.View.VISIBLE);
            rv.setTextViewText(R.id.w_empty, "Пар нет");
            return rv;
        }

        rv.setViewVisibility(R.id.w_empty, android.view.View.GONE);
        rv.setViewVisibility(R.id.w_rows, android.view.View.VISIBLE);

        //Каждому виджету — СВОЙ Intent-адаптер. Данные у них разные (низкий прячет
        //прошедшие пары), а система различает адаптеры по Intent'у целиком, поэтому в
        //него обязан входить и widgetId, и признак showPast. Без widgetId два виджета
        //разных размеров получили бы один и тот же список.
        Intent svc = new Intent(ctx, ScheduleWidgetService.class);
        svc.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        //Высокий виджет показывает и прошедшие пары (приглушённо) — они дают опору
        //«сейчас третья из пяти»; низкий отвечает на «что дальше», и тратить на них
        //свои полторы видимые строки нельзя. Тот же флаг решает оба вопроса.
        svc.putExtra(ScheduleWidgetService.EXTRA_SHOW_PAST, tall);
        svc.setData(android.net.Uri.parse(svc.toUri(Intent.URI_INTENT_SCHEME)));
        rv.setRemoteAdapter(R.id.w_rows, svc);
        rv.setEmptyView(R.id.w_rows, R.id.w_empty);

        //Шаблон клика для строк списка: у элементов коллекции своего PendingIntent быть
        //не может, система склеивает этот шаблон с fill-in из getViewAt.
        Intent open = new Intent(ctx, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        rv.setPendingIntentTemplate(R.id.w_rows,
                PendingIntent.getActivity(ctx, 1, open, flags));
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
