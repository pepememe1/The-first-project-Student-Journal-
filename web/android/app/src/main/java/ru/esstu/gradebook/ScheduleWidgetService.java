package ru.esstu.gradebook;

import android.appwidget.AppWidgetManager;
import android.content.Context;
import android.content.Intent;
import android.util.TypedValue;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;

/**
 * Поставщик строк для ПРОКРУЧИВАЕМОГО списка пар в виджете.
 *
 * ━━ ЗАЧЕМ ПОЯВИЛСЯ ━━
 * Первая версия виджета собирала строки статически (`removeAllViews` + `addView`) и
 * подгоняла ЧИСЛО строк под высоту ячейки. Это работало, пока шрифт был мелким. Как
 * только кегли выросли до читаемых с вытянутой руки, в низкий виджет стало влезать
 * полторы пары — и «показать меньше» перестало быть приемлемым ответом. Единственный
 * способ показать весь день крупным шрифтом на маленькой ячейке — прокрутка, а
 * прокрутка в виджете бывает только через коллекцию (ListView + этот сервис).
 *
 * ⚠️ Плата за прокрутку честная и её стоит помнить: коллекционный виджет просыпается
 * ОТДЕЛЬНЫМ процессом-сервисом, поэтому обновляется заметно медленнее статического и
 * при первом показе может моргнуть пустотой. Ради маленького виджета «что сейчас»
 * (2×2) сервис не используется — там одна пара, списку взяться неоткуда.
 *
 * ⚠️ Данные берём из ТОГО ЖЕ снимка в SharedPreferences, что и провайдер, и НИКОГДА не
 * ходим в сеть отсюда: RemoteViewsFactory вызывается системой на своём потоке с
 * коротким терпением, а виджет по построению работает офлайн (см. ScheduleWidgetData).
 */
public class ScheduleWidgetService extends RemoteViewsService {

    /** Показывать ли прошедшие пары (большой виджет — да, низкий — нет). См. Factory. */
    static final String EXTRA_SHOW_PAST = "ru.esstu.gradebook.SHOW_PAST";

    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        boolean showPast = intent.getBooleanExtra(EXTRA_SHOW_PAST, true);
        //id виджета нужен, чтобы прочитать ЕГО настройки: у двух виджетов на столе они
        //разные, и общий список строк на оба обслуживал бы плохо оба.
        int widgetId = intent.getIntExtra(android.appwidget.AppWidgetManager.EXTRA_APPWIDGET_ID,
                android.appwidget.AppWidgetManager.INVALID_APPWIDGET_ID);
        return new Factory(getApplicationContext(), showPast, widgetId);
    }

    private static class Factory implements RemoteViewsService.RemoteViewsFactory {
        private final Context ctx;
        private final boolean showPast;
        private final int widgetId;
        private final List<ScheduleWidgetData.Pair> rows = new ArrayList<>();
        private int nowIndex = -1;

        Factory(Context ctx, boolean showPast, int widgetId) {
            this.ctx = ctx;
            this.showPast = showPast;
            this.widgetId = widgetId;
        }

        /** Кегль с учётом выбранного человеком масштаба (см. ScheduleWidgetOptions). */
        private float sp(float base) {
            return ScheduleWidgetOptions.scaledSp(base,
                    ScheduleWidgetOptions.textScale(ctx, widgetId));
        }

        @Override
        public void onCreate() { }

        /**
         * Перечитать снимок. Система зовёт этот метод и при первом показе, и после
         * каждого notifyAppWidgetViewDataChanged — то есть при смене пары тоже.
         */
        @Override
        public void onDataSetChanged() {
            rows.clear();
            nowIndex = -1;
            org.json.JSONObject snap = ScheduleWidgetData.snapshot(ctx);
            if (snap == null) {
                return;
            }
            Calendar now = Calendar.getInstance();
            //Какой день показывать — выбирает человек в настройках виджета.
            //⚠️ «Только сегодня» и «только завтра» ищут ИМЕННО ЭТОТ день и, если пар нет,
            //честно показывают пустоту: человек попросил конкретный день, и подставить
            //ему вместо этого послезавтра значило бы ответить не на его вопрос. Режим по
            //умолчанию (SHOW_TODAY_THEN_TOMORROW) — прежнее поведение: ближайший день с
            //парами, чтобы в воскресенье и на каникулах виджет оставался полезным.
            int mode = ScheduleWidgetOptions.mode(ctx, widgetId);
            ScheduleWidgetData.Day day;
            if (mode == ScheduleWidgetOptions.SHOW_TODAY) {
                day = ScheduleWidgetData.dayAt(snap, now, 0);
            } else if (mode == ScheduleWidgetOptions.SHOW_TOMORROW) {
                Calendar t = (Calendar) now.clone();
                t.add(Calendar.DAY_OF_YEAR, 1);
                day = ScheduleWidgetData.dayAt(snap, t, 1);
            } else {
                day = ScheduleWidgetData.nextDayWithPairs(snap, now);
            }
            if (day == null) {
                return;
            }
            int nowMin = ScheduleWidgetData.minutesOfDay(now);
            for (ScheduleWidgetData.Pair p : day.pairs) {
                boolean past = day.offset == 0 && p.endMin >= 0 && nowMin >= p.endMin;
                //Низкий виджет отвечает на вопрос «что дальше», и тратить его две-три
                //видимые строки на уже закончившиеся пары нельзя. Большой отвечает на
                //«как выглядит мой день» — там прошедшие нужны, они дают опору
                //«сейчас третья из пяти», и рисуются приглушённо.
                if (past && !showPast) {
                    continue;
                }
                if (day.offset == 0 && p.startMin >= 0 && p.endMin >= 0
                        && nowMin >= p.startMin && nowMin < p.endMin) {
                    nowIndex = rows.size();
                }
                rows.add(p);
            }
        }

        @Override
        public void onDestroy() {
            rows.clear();
        }

        @Override
        public int getCount() {
            return rows.size();
        }

        @Override
        public RemoteViews getViewAt(int position) {
            if (position < 0 || position >= rows.size()) {
                return null;
            }
            ScheduleWidgetData.Pair p = rows.get(position);
            boolean isNow = position == nowIndex;
            boolean isPast = nowIndex >= 0 && position < nowIndex;
            RemoteViews rv = new RemoteViews(ctx.getPackageName(), R.layout.widget_schedule_row);

            rv.setInt(R.id.row_root, "setBackgroundResource",
                    isNow ? R.drawable.widget_row_bg_now : R.drawable.widget_row_bg);

            //⚠️ INVISIBLE, а не GONE: при GONE строка сузилась бы на ширину стрелки, и
            //весь список дёргался бы вбок при каждой смене пары.
            rv.setViewVisibility(R.id.row_arrow,
                    isNow ? android.view.View.VISIBLE : android.view.View.INVISIBLE);

            //Показываем только НАЧАЛО пары: конец занимает столько же места, а нужен
            //реже. Разделителем на портале бывает и дефис, и оба тире.
            String start = p.time;
            for (int i = 0; i < start.length(); i++) {
                char c = start.charAt(i);
                if (c == '-' || c == '–' || c == '—') {
                    start = start.substring(0, i).trim();
                    break;
                }
            }
            rv.setTextViewText(R.id.row_time, start);
            rv.setTextViewText(R.id.row_pair, isNow ? "идёт" : (p.no + " пара"));
            rv.setTextViewText(R.id.row_subject, p.subject.isEmpty() ? "—" : p.subject);

            //Масштаб текста. Кегли те же, что в разметке, — здесь только множитель:
            //держать «настоящий» размер в двух местах значило бы, что правка в XML молча
            //не подействует на настроенные виджеты.
            rv.setTextViewTextSize(R.id.row_time, TypedValue.COMPLEX_UNIT_SP, sp(16f));
            rv.setTextViewTextSize(R.id.row_pair, TypedValue.COMPLEX_UNIT_SP, sp(11f));
            rv.setTextViewTextSize(R.id.row_subject, TypedValue.COMPLEX_UNIT_SP, sp(16f));
            rv.setTextViewTextSize(R.id.row_meta, TypedValue.COMPLEX_UNIT_SP, sp(12f));
            rv.setTextViewTextSize(R.id.row_room, TypedValue.COMPLEX_UNIT_SP, sp(14f));

            StringBuilder meta = new StringBuilder();
            //Подгруппа идёт ПЕРВОЙ в подписи: когда в одно время стоят две пары, это
            //единственное, что отвечает на вопрос «которая моя».
            if (p.subgroup > 0) {
                meta.append(p.subgroup).append(" п/г");
            }
            if (!p.kind.isEmpty()) {
                if (meta.length() > 0) {
                    meta.append(" · ");
                }
                meta.append(p.kind);
            }
            if (!p.who.isEmpty()) {
                if (meta.length() > 0) {
                    meta.append(" · ");
                }
                meta.append(p.who);
            }
            //Строку с преподавателем/группой можно выключить: на узком виджете она
            //съедает место, а часть людей и так знает, кто ведёт предмет.
            if (meta.length() == 0 || !ScheduleWidgetOptions.showTeacher(ctx, widgetId)) {
                rv.setViewVisibility(R.id.row_meta, android.view.View.GONE);
            } else {
                rv.setViewVisibility(R.id.row_meta, android.view.View.VISIBLE);
                rv.setTextViewText(R.id.row_meta, meta.toString());
            }

            //⚠️ Аудиторию прячем через GONE, а не пустым текстом: пустой TextView всё
            //равно занимает отступы, и заголовок предмета не расширится на его место.
            if (p.room.isEmpty() || !ScheduleWidgetOptions.showRoom(ctx, widgetId)) {
                rv.setViewVisibility(R.id.row_room, android.view.View.GONE);
            } else {
                rv.setViewVisibility(R.id.row_room, android.view.View.VISIBLE);
                rv.setTextViewText(R.id.row_room, p.room);
            }

            if (isNow) {
                rv.setTextColor(R.id.row_pair, ctx.getResources().getColor(R.color.gb_widget_accent));
            } else if (isPast) {
                //Гасим ЦВЕТОМ, а не прозрачностью: setAlpha у RemoteViews работает не на
                //всех лаунчерах, а цвет — везде одинаково.
                int muted = ctx.getResources().getColor(R.color.gb_widget_past);
                rv.setTextColor(R.id.row_time, muted);
                rv.setTextColor(R.id.row_subject, muted);
                rv.setTextColor(R.id.row_room, muted);
            }

            //Клик по строке открывает приложение. У элементов коллекции своего
            //PendingIntent быть не может (их тысячи) — система склеивает шаблон,
            //заданный провайдером, с этим fill-in.
            rv.setOnClickFillInIntent(R.id.row_root, new Intent());
            return rv;
        }

        @Override
        public RemoteViews getLoadingView() {
            return null;   //системная заглушка подходит: строка появляется мгновенно
        }

        @Override
        public int getViewTypeCount() {
            return 1;
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public boolean hasStableIds() {
            //false: при смене пары порядок и состав строк меняются (низкий виджет
            //выбрасывает прошедшие), и «стабильный» id ввёл бы систему в заблуждение.
            return false;
        }
    }
}
