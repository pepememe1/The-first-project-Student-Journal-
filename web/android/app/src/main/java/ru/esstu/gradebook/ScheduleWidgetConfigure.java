package ru.esstu.gradebook;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.SeekBar;
import android.widget.TextView;

/**
 * Экран настройки виджета расписания.
 *
 * ━━ ДВА ПОВОДА ОТКРЫТЬСЯ ━━
 * 1. Система зовёт его САМА при добавлении виджета (`android:configure` в
 *    schedule_widget_info.xml). В этом случае отмена означает, что виджета не будет
 *    вовсе — Android удалит заготовку, если мы не вернём RESULT_OK.
 * 2. Человек нажал шестерёнку на уже стоящем виджете. Здесь отмена ничего не удаляет.
 *
 * Разметка одна на оба случая, отличается только надпись на кнопке подтверждения:
 * «Добавить» против «Сохранить». Разница не косметическая — в первом случае человек
 * должен понимать, что нажатие «Отмена» отменяет саму установку.
 *
 * ━━ ГЛАВНАЯ ЛОВУШКА ━━
 * 🔥 РЕЗУЛЬТАТ НАДО ВЫСТАВИТЬ RESULT_CANCELED ПЕРВОЙ СТРОКОЙ `onCreate`. Если человек
 * закроет экран кнопкой «назад» (а он закроет — это самый частый способ передумать), без
 * этого система получит неопределённый результат и в части прошивок оставит на столе
 * ПУСТОЙ, неработающий виджет. Порядок здесь значим, и это не перестраховка: так
 * задокументировано в самом Android и так же ведут себя системные виджеты.
 */
public class ScheduleWidgetConfigure extends Activity {

    /**
     * Ниже этого фон перестаёт отделять текст от обоев.
     *
     * ⚠️ Ограничение НЕ косметическое: выкрутив прозрачность в ноль, человек получает
     * невидимый виджет и вернуть настройку может только вслепую — попав пальцем в
     * шестерёнку, которой не видно. Из такого состояния выходят удалением виджета, то
     * есть теряют и его настройки. 15 % — та граница, где подложка ещё читается на
     * светлых обоях.
     */
    private static final int MIN_ALPHA = 15;

    private int widgetId = AppWidgetManager.INVALID_APPWIDGET_ID;
    private boolean fromSystem;      //экран открыт при ДОБАВЛЕНИИ виджета

    private RadioGroup modeGroup;
    private RadioGroup textGroup;
    private SeekBar alphaBar;
    private TextView alphaValue;
    private CheckBox teacherBox;
    private CheckBox roomBox;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        //🔥 ПЕРВОЙ СТРОКОЙ — см. «главная ловушка» в шапке класса.
        setResult(RESULT_CANCELED);

        Intent intent = getIntent();
        Bundle extras = intent != null ? intent.getExtras() : null;
        if (extras != null) {
            widgetId = extras.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID,
                    AppWidgetManager.INVALID_APPWIDGET_ID);
        }
        //Система при добавлении зовёт нас с ACTION_APPWIDGET_CONFIGURE; шестерёнка виджета
        //шлёт свой Intent без этого действия. По нему и различаем поводы.
        fromSystem = intent != null
                && AppWidgetManager.ACTION_APPWIDGET_CONFIGURE.equals(intent.getAction());

        if (widgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            //Без id настраивать нечего. Тихо закрываемся: показывать ошибку человеку,
            //который ничего не делал неправильно, незачем.
            finish();
            return;
        }

        setContentView(R.layout.widget_configure);
        bindViews();
        fillFromSaved();
    }

    private void bindViews() {
        modeGroup = findViewById(R.id.cfg_mode);
        textGroup = findViewById(R.id.cfg_text);
        alphaBar = findViewById(R.id.cfg_alpha);
        alphaValue = findViewById(R.id.cfg_alpha_value);
        teacherBox = findViewById(R.id.cfg_teacher);
        roomBox = findViewById(R.id.cfg_room);

        Button save = findViewById(R.id.cfg_save);
        save.setText(fromSystem ? R.string.wcfg_add : R.string.wcfg_save);
        save.setOnClickListener(v -> apply());
        findViewById(R.id.cfg_cancel).setOnClickListener(v -> finish());

        alphaBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar bar, int value, boolean byUser) {
                if (byUser && value < MIN_ALPHA) {
                    //Не даём уйти ниже порога: возвращаем ползунок, а не «сохраняем как
                    //есть». Молча принять 0 значило бы отдать человеку невидимый виджет.
                    bar.setProgress(MIN_ALPHA);
                    return;
                }
                alphaValue.setText(getString(R.string.wcfg_percent, bar.getProgress()));
            }

            @Override
            public void onStartTrackingTouch(SeekBar bar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar bar) {
            }
        });
    }

    /** Заполнить экран тем, что уже сохранено (при повторной настройке — прежним). */
    private void fillFromSaved() {
        int mode = ScheduleWidgetOptions.mode(this, widgetId);
        ((RadioButton) findViewById(
                mode == ScheduleWidgetOptions.SHOW_TODAY ? R.id.cfg_mode_today
                        : mode == ScheduleWidgetOptions.SHOW_TOMORROW ? R.id.cfg_mode_tomorrow
                        : R.id.cfg_mode_auto)).setChecked(true);

        int text = ScheduleWidgetOptions.textScale(this, widgetId);
        ((RadioButton) findViewById(
                text == ScheduleWidgetOptions.TEXT_SMALL ? R.id.cfg_text_small
                        : text == ScheduleWidgetOptions.TEXT_LARGE ? R.id.cfg_text_large
                        : R.id.cfg_text_normal)).setChecked(true);

        int alpha = Math.max(MIN_ALPHA, ScheduleWidgetOptions.alpha(this, widgetId));
        alphaBar.setProgress(alpha);
        alphaValue.setText(getString(R.string.wcfg_percent, alpha));

        teacherBox.setChecked(ScheduleWidgetOptions.showTeacher(this, widgetId));
        roomBox.setChecked(ScheduleWidgetOptions.showRoom(this, widgetId));
    }

    private void apply() {
        int mode = modeGroup.getCheckedRadioButtonId() == R.id.cfg_mode_today
                ? ScheduleWidgetOptions.SHOW_TODAY
                : modeGroup.getCheckedRadioButtonId() == R.id.cfg_mode_tomorrow
                ? ScheduleWidgetOptions.SHOW_TOMORROW
                : ScheduleWidgetOptions.SHOW_TODAY_THEN_TOMORROW;

        int text = textGroup.getCheckedRadioButtonId() == R.id.cfg_text_small
                ? ScheduleWidgetOptions.TEXT_SMALL
                : textGroup.getCheckedRadioButtonId() == R.id.cfg_text_large
                ? ScheduleWidgetOptions.TEXT_LARGE
                : ScheduleWidgetOptions.TEXT_NORMAL;

        ScheduleWidgetOptions.save(this, widgetId, mode,
                Math.max(MIN_ALPHA, alphaBar.getProgress()), text,
                teacherBox.isChecked(), roomBox.isChecked());

        //Перерисовать НЕМЕДЛЕННО: иначе новые настройки появятся только через полчаса
        //(`updatePeriodMillis` реже не бывает), и человек решит, что они не сохранились.
        ScheduleWidgetProvider.refreshAll(this);

        Intent result = new Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId);
        setResult(RESULT_OK, result);
        finish();
    }
}
