package ru.esstu.gradebook;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Настройки ОДНОГО размещённого виджета расписания.
 *
 * ━━ ЗАЧЕМ ━━
 * До 01.09.2026 виджет был один на всех и не настраивался вовсе: что показывать, каким
 * шрифтом и насколько прозрачно — решал код. На практике люди держат на экране РАЗНЫЕ
 * виджеты по разным поводам: один маленький «что сейчас» поверх обоев, другой большой
 * «весь день» на отдельном экране. Одна раскладка на оба случая обслуживает плохо оба.
 *
 * ━━ ПОЧЕМУ НАСТРОЙКИ НА КАЖДЫЙ ВИДЖЕТ, А НЕ ОБЩИЕ ━━
 * Ключ включает `appWidgetId`. Общая настройка означала бы, что человек, поставивший два
 * виджета, не может сделать их разными, — а именно ради разного их и ставят два. Цена:
 * при удалении виджета его настройки надо убирать, иначе они копятся мусором и однажды
 * достанутся ЧУЖОМУ виджету с тем же id (система переиспользует номера). Убирает
 * `clear()` из `onDeleted`.
 *
 * ⚠️ Значения по умолчанию — это поведение ДО появления настроек, до последней мелочи.
 * Иначе обновление приложения молча переставит всем уже размещённые виджеты, и человек
 * решит, что что-то сломалось.
 */
final class ScheduleWidgetOptions {

    /** Что показывать в списке. */
    static final int SHOW_TODAY = 0;
    /** Сегодня, а после конца пар — завтра. Поведение по умолчанию (как было всегда). */
    static final int SHOW_TODAY_THEN_TOMORROW = 1;
    /** Только завтра — для тех, кто смотрит расписание вечером. */
    static final int SHOW_TOMORROW = 2;

    /** Масштаб текста в процентах. 100 — как было. */
    static final int TEXT_NORMAL = 100;
    static final int TEXT_LARGE = 118;
    static final int TEXT_SMALL = 88;

    private static final String K_MODE = "opt_mode_";
    private static final String K_ALPHA = "opt_alpha_";
    private static final String K_TEXT = "opt_text_";
    private static final String K_TEACHER = "opt_teacher_";
    private static final String K_ROOM = "opt_room_";

    private ScheduleWidgetOptions() {
    }

    private static SharedPreferences prefs(Context ctx) {
        //Тот же файл, что у снимка расписания: заводить второй ради пяти ключей незачем,
        //а при чистке данных приложения они и так уходят вместе.
        return ScheduleWidgetData.prefs(ctx);
    }

    /** Что показывать: SHOW_*. */
    static int mode(Context ctx, int widgetId) {
        return prefs(ctx).getInt(K_MODE + widgetId, SHOW_TODAY_THEN_TOMORROW);
    }

    /**
     * Непрозрачность фона, 0..100. По умолчанию 100 — сплошная подложка, как было.
     *
     * ⚠️ Ниже 15 % фон перестаёт отделять текст от обоев, и виджет становится
     * нечитаемым на светлой картинке. Ограничение стоит в экране настройки, а не здесь:
     * тут только чтение, и молча «поправлять» сохранённое значение нельзя — человек
     * увидел бы не то, что выбрал.
     */
    static int alpha(Context ctx, int widgetId) {
        return prefs(ctx).getInt(K_ALPHA + widgetId, 100);
    }

    /** Масштаб текста в процентах (TEXT_*). */
    static int textScale(Context ctx, int widgetId) {
        return prefs(ctx).getInt(K_TEXT + widgetId, TEXT_NORMAL);
    }

    /** Показывать ли преподавателя (у студента) / группу (у преподавателя). */
    static boolean showTeacher(Context ctx, int widgetId) {
        return prefs(ctx).getBoolean(K_TEACHER + widgetId, true);
    }

    /** Показывать ли аудиторию. */
    static boolean showRoom(Context ctx, int widgetId) {
        return prefs(ctx).getBoolean(K_ROOM + widgetId, true);
    }

    static void save(Context ctx, int widgetId, int mode, int alpha, int textScale,
                     boolean showTeacher, boolean showRoom) {
        prefs(ctx).edit()
                .putInt(K_MODE + widgetId, mode)
                .putInt(K_ALPHA + widgetId, alpha)
                .putInt(K_TEXT + widgetId, textScale)
                .putBoolean(K_TEACHER + widgetId, showTeacher)
                .putBoolean(K_ROOM + widgetId, showRoom)
                .apply();
    }

    /**
     * Убрать настройки удалённого виджета.
     *
     * ⚠️ Обязательно, и не ради экономии места: система ПЕРЕИСПОЛЬЗУЕТ номера виджетов.
     * Оставленные настройки однажды достанутся новому виджету, и он появится на экране
     * уже настроенным неизвестно кем — а объяснить это человеку будет нечем.
     */
    static void clear(Context ctx, int widgetId) {
        prefs(ctx).edit()
                .remove(K_MODE + widgetId)
                .remove(K_ALPHA + widgetId)
                .remove(K_TEXT + widgetId)
                .remove(K_TEACHER + widgetId)
                .remove(K_ROOM + widgetId)
                .apply();
    }

    /**
     * Цвет подложки с учётом выбранной непрозрачности.
     *
     * @param baseColor цвет из ресурсов (ARGB, альфа в нём игнорируется)
     */
    static int tintBackground(int baseColor, int alphaPercent) {
        int a = Math.round(255f * Math.max(0, Math.min(100, alphaPercent)) / 100f);
        return (a << 24) | (baseColor & 0x00FFFFFF);
    }

    /**
     * Кегль с учётом масштаба.
     *
     * ⚠️ Округляем к БЛИЖАЙШЕМУ, а не вниз: при масштабе 88 % кегль 11sp дал бы 9sp
     * усечением и 10sp округлением — разница в один пиксель здесь заметна, потому что
     * это самая мелкая подпись виджета («2 пара»), и она уже на границе читаемости.
     */
    static float scaledSp(float baseSp, int scalePercent) {
        return Math.round(baseSp * scalePercent / 100f * 10f) / 10f;
    }
}
