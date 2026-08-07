package ru.esstu.gradebook;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Calendar;
import java.util.TimeZone;

/**
 * Джавовая половина контракта чётности учебной недели.
 *
 * Пара к `tests/test_week_parity_contract.py`: обе стороны читают ОДИН файл
 * `docs/contracts/week-parity-cases.json`, сгенерированный из питоновского источника
 * правды (`server/app/schedule_web.py::current_week_parity`).
 *
 * Зачем вообще: виджет считает неделю САМ (расписание рисуется из кэша, без запросов
 * к серверу — токен в проекте живёт жёстко 5 часов), поэтому копия формулы на Java
 * неизбежна. Сдвиг на один день здесь переворачивает чётность и показывает человеку
 * расписание ЧУЖОЙ недели — правдоподобное и потому особенно вредное.
 *
 * Запуск: `cd web/android && ./gradlew testDebugUnitTest`. Это JVM-тест, устройство
 * и эмулятор не нужны.
 */
public class WeekParityContractTest {

    /**
     * Путь до контракта от корня android-проекта.
     *
     * Тест выполняется с рабочим каталогом `web/android/app`, поэтому до корня
     * монорепо — три уровня вверх. Если файла нет, тест ПАДАЕТ, а не пропускается:
     * молча пропущенный контракт — это отсутствующий контракт.
     */
    private static JSONArray cases() throws Exception {
        File f = new File("../../../docs/contracts/week-parity-cases.json");
        assertTrue("не найден файл контракта: " + f.getAbsolutePath(), f.exists());
        String raw = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
        return new JSONObject(raw).getJSONArray("cases");
    }

    private static Calendar calendarOf(String iso) {
        String[] parts = iso.split("-");
        Calendar c = Calendar.getInstance(TimeZone.getDefault());
        c.clear();
        c.set(Integer.parseInt(parts[0]), Integer.parseInt(parts[1]) - 1, Integer.parseInt(parts[2]),
                12, 0, 0);   //полдень: подальше от границ суток и переводов часов
        return c;
    }

    @Test
    public void javaMatchesContract() throws Exception {
        JSONArray cases = cases();
        assertTrue("случаев слишком мало", cases.length() >= 20);
        for (int i = 0; i < cases.length(); i++) {
            JSONObject c = cases.getJSONObject(i);
            String iso = c.getString("date");
            assertEquals("чётность разошлась с контрактом на " + iso,
                    c.getInt("parity"), ScheduleWidgetData.weekParity(calendarOf(iso)));
        }
    }

    /**
     * Страховка от бессмысленного теста: сдвинутая на день формула ОБЯЗАНА
     * контракт провалить. Иначе он был бы зелёным при любой реализации.
     */
    @Test
    public void shiftedFormulaWouldFail() throws Exception {
        JSONArray cases = cases();
        int mismatches = 0;
        for (int i = 0; i < cases.length(); i++) {
            JSONObject c = cases.getJSONObject(i);
            Calendar cal = calendarOf(c.getString("date"));
            cal.add(Calendar.DAY_OF_YEAR, 1);
            if (ScheduleWidgetData.weekParity(cal) != c.getInt("parity")) {
                mismatches++;
            }
        }
        assertTrue("сдвинутая формула прошла бы контракт — он бесполезен", mismatches > 0);
    }

    /** Внутри одной недели чётность постоянна, между соседними — меняется. */
    @Test
    public void parityIsStableInsideWeekAndFlipsBetween() {
        Calendar monday = calendarOf("2026-02-02");        //понедельник
        int first = ScheduleWidgetData.weekParity(monday);
        for (int i = 1; i < 6; i++) {                       //Втр..Сбт той же недели
            Calendar c = (Calendar) monday.clone();
            c.add(Calendar.DAY_OF_YEAR, i);
            assertEquals("чётность не должна меняться внутри недели",
                    first, ScheduleWidgetData.weekParity(c));
        }
        Calendar nextMonday = (Calendar) monday.clone();
        nextMonday.add(Calendar.DAY_OF_YEAR, 7);
        assertTrue("чётность обязана смениться на следующей неделе",
                first != ScheduleWidgetData.weekParity(nextMonday));
    }

    /** Разбор «10:45-12:20» — от него зависит подсветка идущей пары. */
    @Test
    public void parsesPairTimeSpan() {
        assertEquals(10 * 60 + 45, ScheduleWidgetData.parseSpan("10:45-12:20")[0]);
        assertEquals(12 * 60 + 20, ScheduleWidgetData.parseSpan("10:45-12:20")[1]);
        //Тире вместо дефиса встречается на портале наравне с дефисом.
        assertEquals(9 * 60, ScheduleWidgetData.parseSpan("09:00–10:35")[0]);
        //Не разобралось — пара всё равно покажется, просто без «идёт сейчас».
        assertEquals(-1, ScheduleWidgetData.parseSpan("")[0]);
        assertEquals(-1, ScheduleWidgetData.parseSpan("по расписанию")[0]);
    }
}
