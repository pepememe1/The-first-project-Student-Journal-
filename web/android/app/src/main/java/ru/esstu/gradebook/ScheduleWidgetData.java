package ru.esstu.gradebook;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;

/**
 * Данные виджета расписания: кэш, разрешение «какой сегодня день» и разбор времени пар.
 *
 * ━━ ПОЧЕМУ ВИДЖЕТ НЕ ХОДИТ В СЕТЬ САМ ━━
 * Соблазнительно было бы дать виджету токен и обновляться самому. Так делать НЕЛЬЗЯ:
 * JWT в проекте живёт ЖЁСТКО 5 часов (и access, и refresh — см. §6 в доке команды),
 * после чего нового токена без пароля не получить. Виджет, который «работает первые
 * пять часов после входа, а потом молча показывает ошибку», хуже отсутствующего.
 *
 * Поэтому снимок кладёт ПРИЛОЖЕНИЕ (мост GradeBookWidgetNative, см. MainActivity), а
 * виджет — чистый рендер поверх кэша. Это не компромисс, а совпадение с природой
 * данных: расписание портала ВСГУТУ недельное и меняется редко, а «какая пара идёт
 * сейчас» и «какой сегодня день» считаются локально из той же недельной сетки и
 * остаются верными сколько угодно долго без единого запроса.
 *
 * ━━ ЧЁТНОСТЬ НЕДЕЛИ ━━
 * Порт `schedule_web.current_week_parity` / `schedule/store.py` — ОДНА И ТА ЖЕ
 * арифметика, третьей копии правила заводить нельзя. Согласованность держит контракт
 * `docs/contracts/week-parity-cases.json`: те же даты проверяет питоновский тест и
 * джавовый (app/src/test/.../WeekParityContractTest.java).
 */
final class ScheduleWidgetData {

    static final String PREFS = "gb_widget";
    /** JSON-снимок расписания, положенный веб-слоем. */
    static final String KEY_SNAPSHOT = "snapshot";

    /** Короткие имена дней — тот же порядок и та же запись, что в schedule/model.py. */
    static final String[] WEEKDAYS = {"Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"};

    private static final String[] DAY_FULL = {
            "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"};
    private static final String[] MONTHS_GEN = {
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"};

    private ScheduleWidgetData() {
    }

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Снимок или null, если приложение ещё ни разу не положило данные. */
    static JSONObject snapshot(Context ctx) {
        String raw = prefs(ctx).getString(KEY_SNAPSHOT, "");
        if (raw == null || raw.isEmpty()) {
            return null;
        }
        try {
            return new JSONObject(raw);
        } catch (Exception e) {
            return null;   //повреждённый кэш — ведём себя как «данных нет», а не падаем
        }
    }

    /**
     * 1 (I неделя) / 2 (II неделя).
     *
     * Порт `schedule_web.current_week_parity` / `schedule/store.py` — третья копия
     * одной арифметики, и другого пути нет: виджет считает неделю сам, спросить ему
     * не у кого. Согласованность держит `docs/contracts/week-parity-cases.json`.
     *
     * 🔥 ИСПРАВЛЕНО 31.08.2026: считаем от начала УЧЕБНОГО года, как портал, а не
     * «номер недели с 1 января». Прежняя формула расходилась с порталом ровно на
     * неделю — виджет на экране телефона показывал расписание ЧУЖОЙ недели, и это
     * ХУЖЕ, чем пустой виджет: пустой заставляет открыть приложение, а неверный
     * выглядит рабочим. Исходник правила — `portal.esstu.ru/menu.htm`,
     * `getReferenceDate()` / `getWeekNum()`.
     */
    static int weekParity(Calendar cal) {
        Calendar ref = academicWeekStart(cal);
        //Целые сутки между датами: обе величины приводим к полуночи, иначе разница
        //поедет от времени суток и на границе недели чётность перевернётся.
        long days = Math.round((midnight(cal) - midnight(ref)) / 86400000.0);
        double diff = days / 7.0;
        if (diff >= 0) return ((long) diff) % 2 == 0 ? 1 : 2;
        //Ветка «до точки отсчёта» у портала своя и несимметричная — переносим как есть.
        return ((long) (diff + 1.0 / 7.0)) % 2 == 0 ? 2 : 1;
    }

    /** Понедельник первой учебной недели полугодия — порт `getReferenceDate()`. */
    static Calendar academicWeekStart(Calendar cal) {
        int year = cal.get(Calendar.YEAR);
        //Январь-июль — весеннее полугодие, точка отсчёта в ПРОШЛОМ учебном году.
        int refYear = (cal.get(Calendar.MONTH) <= Calendar.JULY) ? year - 1 : year;
        Calendar sep1 = (Calendar) cal.clone();
        sep1.set(refYear, Calendar.SEPTEMBER, 1);
        int dow = sep1.get(Calendar.DAY_OF_WEEK) - 1;            // Calendar: 1=Вс → 0=Вс
        Calendar out = (Calendar) sep1.clone();
        if (dow == 1) out.set(refYear, Calendar.SEPTEMBER, 1);
        else if (dow >= 2 && dow <= 5) out.set(refYear, Calendar.AUGUST, 31 - dow + 2);
        else if (dow == 6) out.set(refYear, Calendar.SEPTEMBER, 3);
        else out.set(refYear, Calendar.SEPTEMBER, 2);
        return out;
    }

    /** Полночь той же даты — чтобы разница считалась в сутках, а не в часах. */
    private static long midnight(Calendar cal) {
        Calendar c = (Calendar) cal.clone();
        c.set(Calendar.HOUR_OF_DAY, 0);
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        return c.getTimeInMillis();
    }

    /** «Пнд».. «Сбт», либо null для воскресенья (в расписании колледжа его нет). */
    static String weekdayKey(Calendar cal) {
        int dow = cal.get(Calendar.DAY_OF_WEEK);               // 1=Вс … 7=Сб
        if (dow == Calendar.SUNDAY) {
            return null;
        }
        return WEEKDAYS[dow - Calendar.MONDAY];
    }

    /** «понедельник».. «воскресенье». */
    static String weekdayFull(Calendar cal) {
        int dow = cal.get(Calendar.DAY_OF_WEEK);
        return dow == Calendar.SUNDAY ? DAY_FULL[6] : DAY_FULL[dow - Calendar.MONDAY];
    }

    /** «7 августа» — родительный падеж, как в интерфейсе продукта. */
    static String dateHuman(Calendar cal) {
        return cal.get(Calendar.DAY_OF_MONTH) + " " + MONTHS_GEN[cal.get(Calendar.MONTH)];
    }

    static String isoDate(Calendar cal) {
        return String.format(Locale.US, "%04d-%02d-%02d",
                cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, cal.get(Calendar.DAY_OF_MONTH));
    }

    /**
     * Ключ дня внутри снимка.
     *
     * Категорий расписания на портале две по устройству (см. schedule/parser.py):
     * обычная недельная сетка (колледж, бакалавриат) — ключ «чётность|день», и
     * СЕССИОННАЯ (заочные), где днями выступают календарные даты. Веб-слой приводит
     * обе к одному виду и помечает `kind`, поэтому здесь остаётся только выбрать
     * форму ключа, а не разбирать два формата расписания заново.
     */
    static String dayKey(JSONObject snap, Calendar cal) {
        if ("dated".equals(snap.optString("kind"))) {
            return isoDate(cal);
        }
        String wd = weekdayKey(cal);
        return wd == null ? null : (weekParity(cal) + "|" + wd);
    }

    /** Одна пара в удобном для рендера виде. */
    static final class Pair {
        int no;                 //номер пары (1..8)
        String time = "";       //«10:45-12:20» как на портале
        String subject = "";
        String kind = "";       //лек/пр/лаб — как распознал парсер, может быть пустым
        String room = "";
        String who = "";        //преподаватель (у студента) или группа (у преподавателя)
        int subgroup = 0;       //0 — вся группа, 1|2 — подгруппа (см. parse_cell_all)
        int startMin = -1;      //минуты от полуночи; -1 — время не разобралось
        int endMin = -1;
    }

    /**
     * День с парами.
     * `offset` — на сколько суток вперёд от сегодня (0 = сегодня, 1 = завтра …).
     */
    static final class Day {
        Calendar date;
        int offset;
        final List<Pair> pairs = new ArrayList<>();
    }

    /**
     * Ближайший день с парами, начиная с сегодняшнего.
     *
     * Заглядываем вперёд на неделю: в воскресенье, на каникулах и просто в пустой
     * день показывать «Пар нет» и обрывать разговор — значит заставить человека
     * открыть приложение ровно за тем, что виджет и так знает. Ничего не нашли за
     * 7 дней — возвращаем сегодняшний пустой день, честно.
     */
    static Day nextDayWithPairs(JSONObject snap, Calendar from) {
        Day today = null;
        for (int i = 0; i <= 7; i++) {
            Calendar c = (Calendar) from.clone();
            c.add(Calendar.DAY_OF_YEAR, i);
            Day d = dayAt(snap, c, i);
            if (i == 0) {
                today = d;
            }
            if (!d.pairs.isEmpty()) {
                return d;
            }
        }
        return today;
    }

    static Day dayAt(JSONObject snap, Calendar cal, int offset) {
        Day day = new Day();
        day.date = cal;
        day.offset = offset;
        String key = dayKey(snap, cal);
        if (key == null) {
            return day;      //воскресенье в недельной сетке — пар не бывает
        }
        JSONObject days = snap.optJSONObject("days");
        if (days == null) {
            return day;
        }
        JSONArray arr = days.optJSONArray(key);
        if (arr == null) {
            return day;
        }
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) {
                continue;
            }
            Pair p = new Pair();
            p.no = o.optInt("n", i + 1);
            p.time = o.optString("t", "");
            p.subject = o.optString("s", "");
            p.kind = o.optString("k", "");
            p.room = o.optString("r", "");
            p.who = o.optString("w", "");
            //Подгруппа (0 — вся группа). Портал кладёт занятия обеих подгрупп в ОДНУ
            //клетку, и в виджете они идут двумя строками в одно время — без этой метки
            //человек не поймёт, которая из них его.
            p.subgroup = o.optInt("g", 0);
            int[] span = parseSpan(p.time);
            p.startMin = span[0];
            p.endMin = span[1];
            day.pairs.add(p);
        }
        return day;
    }

    /**
     * «10:45-12:20» → минуты от полуночи. Разделителем на портале встречается и
     * дефис, и тире — берём любой нецифровой разрыв, а не перечисляем варианты:
     * промах разбора здесь означает потерянную подсветку текущей пары, и ради этого
     * не стоит зависеть от того, каким именно знаком набрана строка на чужом сайте.
     *
     * Не разобралось — {-1,-1}: пара всё равно покажется, просто без «идёт сейчас».
     */
    static int[] parseSpan(String time) {
        int[] out = {-1, -1};
        if (time == null) {
            return out;
        }
        List<Integer> nums = new ArrayList<>(4);
        int cur = -1;
        for (int i = 0; i < time.length(); i++) {
            char ch = time.charAt(i);
            if (ch >= '0' && ch <= '9') {
                cur = (cur < 0 ? 0 : cur) * 10 + (ch - '0');
            } else if (cur >= 0) {
                nums.add(cur);
                cur = -1;
            }
        }
        if (cur >= 0) {
            nums.add(cur);
        }
        if (nums.size() >= 2) {
            out[0] = nums.get(0) * 60 + nums.get(1);
        }
        if (nums.size() >= 4) {
            out[1] = nums.get(2) * 60 + nums.get(3);
        }
        return out;
    }

    static int minutesOfDay(Calendar cal) {
        return cal.get(Calendar.HOUR_OF_DAY) * 60 + cal.get(Calendar.MINUTE);
    }
}
