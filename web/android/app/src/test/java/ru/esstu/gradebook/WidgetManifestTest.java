package ru.esstu.gradebook;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * ВИДЕН ЛИ ВИДЖЕТ В СПИСКЕ ДОБАВЛЕНИЯ — проверка объявлений, а не поведения.
 *
 * ━━ ЧЕМ КУПЛЕН ━━
 * 01.09.2026: «друг вообще не видел виджетов и не мог их поставить». Причин оказалось
 * ДВЕ, и обе — в объявлениях, то есть ни один тест кода их поймать не мог:
 *
 *   1. приёмники виджета стояли с `android:exported="false"`. Список виджетов рисует
 *      ЛАУНЧЕР, а широковещательные сообщения шлёт СИСТЕМА — оба сторонние для нас
 *      приложения, и с закрытым экспортом часть оболочек (MIUI, EMUI, ColorOS) виджет не
 *      показывает вовсе;
 *   2. был только `android:previewLayout` — атрибут API 31+. На Android 7–11 (у нас
 *      `minSdkVersion = 24`) лаунчер ищет `android:previewImage`, и без него в списке
 *      либо иконка приложения, либо пусто.
 *
 * Оба случая невидимы на устройстве разработчика с новым Android и свежим лаунчером —
 * именно поэтому здесь тест, а не «проверим глазами».
 */
public class WidgetManifestTest {

    private static final Path RES = Paths.get("src", "main", "res");
    private static final Path MANIFEST = Paths.get("src", "main", "AndroidManifest.xml");

    private static String read(Path p) throws IOException {
        return new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
    }

    /** Все объявления `<receiver …ScheduleWidget…>` вместе с их атрибутами. */
    private static List<String> widgetReceivers(String manifest) {
        List<String> out = new ArrayList<>();
        Matcher m = Pattern.compile("<receiver\\b[^>]*?ScheduleWidget[^>]*?>", Pattern.DOTALL)
                .matcher(manifest);
        while (m.find()) {
            out.add(m.group());
        }
        return out;
    }

    @Test
    public void widgetReceiversAreExported() throws IOException {
        String manifest = read(MANIFEST);
        List<String> receivers = widgetReceivers(manifest);
        assertFalse("приёмники виджета пропали из манифеста — виджета не будет вовсе",
                receivers.isEmpty());
        for (String r : receivers) {
            assertTrue(
                    "приёмник виджета не экспортирован — на части оболочек он не появится "
                            + "в списке добавления, и поставить виджет будет нельзя: " + r,
                    r.contains("android:exported=\"true\""));
        }
    }

    @Test
    public void everyWidgetHasBothPreviews() throws IOException {
        List<Path> infos = new ArrayList<>();
        try (java.util.stream.Stream<Path> files = Files.list(RES.resolve("xml"))) {
            files.filter(p -> p.getFileName().toString().startsWith("schedule_widget"))
                    .forEach(infos::add);
        }
        assertFalse("описания виджетов пропали", infos.isEmpty());
        for (Path p : infos) {
            String xml = read(p);
            assertTrue(p.getFileName() + ": нет previewImage — на Android до 12 виджет "
                            + "покажется пустым местом или не покажется совсем",
                    xml.contains("android:previewImage="));
            assertTrue(p.getFileName() + ": нет previewLayout — на Android 12+ теряется "
                            + "живой предпросмотр",
                    xml.contains("android:previewLayout="));
        }
    }

    @Test
    public void previewImagesExist() throws IOException {
        List<Path> infos = new ArrayList<>();
        try (java.util.stream.Stream<Path> files = Files.list(RES.resolve("xml"))) {
            files.filter(p -> p.getFileName().toString().startsWith("schedule_widget"))
                    .forEach(infos::add);
        }
        Pattern ref = Pattern.compile("android:previewImage=\"@drawable/([\\w_]+)\"");
        for (Path p : infos) {
            Matcher m = ref.matcher(read(p));
            while (m.find()) {
                String name = m.group(1);
                //Битая ссылка на ресурс роняет СБОРКУ, но только если ресурс не найден
                //нигде; проверяем явно, чтобы причина называлась здесь, а не в aapt.
                boolean found = false;
                try (java.util.stream.Stream<Path> dirs = Files.list(RES)) {
                    for (Path dir : (Iterable<Path>) dirs.filter(Files::isDirectory)::iterator) {
                        if (Files.exists(dir.resolve(name + ".png"))
                                || Files.exists(dir.resolve(name + ".xml"))
                                || Files.exists(dir.resolve(name + ".webp"))) {
                            found = true;
                            break;
                        }
                    }
                }
                assertTrue("превью " + name + " объявлено, но файла нет", found);
            }
        }
    }

    @Test
    public void configureActivityIsExported() throws IOException {
        String manifest = read(MANIFEST);
        Matcher m = Pattern.compile("<activity\\b[^>]*?ScheduleWidgetConfigure[^>]*?>", Pattern.DOTALL)
                .matcher(manifest);
        assertTrue("экран настройки виджета пропал из манифеста", m.find());
        assertTrue("экран настройки не экспортирован — его запускает ЛАУНЧЕР при "
                        + "добавлении виджета, и без экспорта добавление молча ничем не "
                        + "закончится: заготовка исчезнет, ошибки человек не увидит",
                m.group().contains("android:exported=\"true\""));
    }

    @Test
    public void widgetsFitASmallGrid() throws IOException {
        //Лаунчер не покажет виджет, который не помещается в его сетку. Формула Android
        //для n ячеек — 70*n-30 dp, то есть 2 ячейки это 110dp. Всё, что просит больше
        //четырёх ячеек по ширине, на телефонах с сеткой 4 колонки просто не появится.
        Pattern minW = Pattern.compile("android:minWidth=\"(\\d+)dp\"");
        try (java.util.stream.Stream<Path> files = Files.list(RES.resolve("xml"))) {
            for (Path p : (Iterable<Path>) files.filter(
                    x -> x.getFileName().toString().startsWith("schedule_widget"))::iterator) {
                Matcher m = minW.matcher(read(p));
                while (m.find()) {
                    int dp = Integer.parseInt(m.group(1));
                    assertTrue(p.getFileName() + ": minWidth " + dp + "dp требует больше "
                                    + "четырёх ячеек — на телефоне с сеткой 4×N виджет не "
                                    + "появится в списке",
                            dp <= 250);
                }
            }
        }
    }
}
