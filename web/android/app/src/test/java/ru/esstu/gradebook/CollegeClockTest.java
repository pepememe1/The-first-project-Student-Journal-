package ru.esstu.gradebook;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Calendar;
import java.util.TimeZone;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Виджет считает «сегодня» и текущую пару по часам КОЛЛЕДЖА (Улан-Удэ), а не телефона.
 *
 * Пояс телефона подменяется (`TimeZone.setDefault`) — и момент 16.10.2026 00:30 по
 * Улан-Удэ обязан остаться пятницей 16-го, ночь на понедельник — новой неделей. До
 * 15.10.2026 виджет брал `Calendar.getInstance()`, и у телефона в Москве эти ответы
 * были вчерашними.
 */
public class CollegeClockTest {

    @Test
    public void offsetMatchesTheServerModule() throws Exception {
        File f = new File("../../../college_clock.py");
        assertTrue("не найден college_clock.py: " + f.getAbsolutePath(), f.exists());
        String py = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
        Matcher m = Pattern.compile("(?m)^UTC_OFFSET_H = (\\d+)$").matcher(py);
        assertTrue("в college_clock.py нет UTC_OFFSET_H", m.find());
        assertEquals(Integer.parseInt(m.group(1)), ScheduleWidgetData.COLLEGE_UTC_OFFSET_H);
    }

    @Test
    public void collegeDayDoesNotDependOnThePhoneZone() {
        TimeZone before = TimeZone.getDefault();
        try {
            for (String zone : new String[]{"Europe/Moscow", "America/New_York", "UTC", "Asia/Irkutsk"}) {
                TimeZone.setDefault(TimeZone.getTimeZone(zone));
                //16.10.2026 00:30 в Улан-Удэ = 15.10.2026 16:30 UTC.
                Calendar c = ScheduleWidgetData.collegeNow();
                c.setTimeInMillis(1792081800000L);
                assertEquals(zone, 16, c.get(Calendar.DAY_OF_MONTH));
                assertEquals(zone, 0, c.get(Calendar.HOUR_OF_DAY));
                assertEquals(zone, Calendar.FRIDAY, c.get(Calendar.DAY_OF_WEEK));
                assertEquals(zone, "2026-10-16", ScheduleWidgetData.isoDate(c));

                //Ночь на понедельник: 19.10.2026 00:30 в Улан-Удэ — уже новая неделя.
                Calendar mon = ScheduleWidgetData.collegeNow();
                mon.setTimeInMillis(1792341000000L);
                Calendar sun = (Calendar) mon.clone();
                sun.add(Calendar.DAY_OF_YEAR, -1);
                assertEquals(zone, Calendar.MONDAY, mon.get(Calendar.DAY_OF_WEEK));
                assertTrue(zone + ": неделя не сменилась",
                        ScheduleWidgetData.weekParity(mon) != ScheduleWidgetData.weekParity(sun));
            }
        } finally {
            TimeZone.setDefault(before);
        }
    }
}
