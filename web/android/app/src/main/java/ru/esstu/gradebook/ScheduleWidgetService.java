package ru.esstu.gradebook;

import android.appwidget.AppWidgetManager;
import android.content.Context;
import android.content.Intent;
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
        return new Factory(getApplicationContext(), showPast);
    }

    private static class Factory implements RemoteViewsService.RemoteViewsFactory {
        private final Context ctx;
        private final boolean showPast;
        private final List<ScheduleWidgetData.Pair> rows = new ArrayList<>();
        private int nowIndex = -1;

        Factory(Context ctx, boolean showPast) {
            this.ctx = ctx;
            this.showPast = showPast;
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
            ScheduleWidgetData.Day day = ScheduleWidgetData.nextDayWithPairs(snap, now);
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

            if (p.room.isEmpty()) {
                rv.setViewVisibility(R.id.row_room, android.view.View.GONE);
            } else {
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
