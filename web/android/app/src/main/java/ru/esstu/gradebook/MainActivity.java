package ru.esstu.gradebook;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.webkit.JavascriptInterface;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.BridgeActivity;

import org.json.JSONObject;

import ru.rustore.sdk.core.tasks.OnFailureListener;
import ru.rustore.sdk.core.tasks.OnSuccessListener;
import ru.rustore.sdk.pushclient.RuStorePushClient;

/**
 * Точка входа приложения + МОСТ между нативными пушами и веб-слоем.
 *
 * ━━ ПОЧЕМУ МОСТ ЖИВЁТ ТОЛЬКО В addJavascriptInterface ━━
 * Раньше здесь через evaluateJavascript создавался объект `window.GradeBookPush` — и
 * это была причина, по которой пуши НЕ РАБОТАЛИ НИ У КОГО (в боевой базе не было ни
 * одного токена устройства). Любая загрузка документа создаёт `window` заново, а
 * подмена веб-бандла (Capgo OTA) — тем более. Скрипт выполнялся один раз при старте
 * окна, ДО загрузки страницы, и к моменту запуска Vue объекта уже не существовало:
 * `registerToken()` молча выходил, потому что «моста нет».
 *
 * Объект, зарегистрированный через addJavascriptInterface, Android подставляет в
 * КАЖДЫЙ новый документ сам. Поэтому единственный мост — `window.GradeBookPushNative`,
 * а обёртку веб-слой строит у себя (см. web/src/services/push.js).
 *
 * ━━ ПОЧЕМУ НАЖАТИЕ ЗАБИРАЮТ, А НЕ ОТДАЮТ ━━
 * Нажатие на уведомление случается, когда приложение может быть вообще не запущено, а
 * веб-слой поднимется через несколько секунд после этого. Колбэк «натив зовёт JS» в
 * таких условиях — гонка. Поэтому событие кладётся в SharedPreferences (переживает
 * даже смерть процесса), а веб-слой ЗАБИРАЕТ его, когда готов.
 *
 * Токен НЕ отправляется на сервер отсюда: здесь нет сессии пользователя, а телефон
 * должен принадлежать ПОСЛЕДНЕМУ вошедшему аккаунту — иначе студент, вошедший после
 * друга, получал бы чужие уведомления.
 */
public class MainActivity extends BridgeActivity {

    private static final String TAG = "GradeBookPush";
    private static final int REQ_NOTIFICATIONS = 4201;

    static final String PREFS = "gb_push";
    static final String KEY_TOKEN = "token";
    /** event_id нажатого уведомления, которое веб-слой ещё не забрал. */
    static final String KEY_PENDING_TAP = "pending_tap";
    /** Почему токена нет — показывается в «Настройках», чтобы отказ был виден. */
    static final String KEY_LAST_ERROR = "last_error";

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new PushBridge(), "GradeBookPushNative");
        getBridge().getWebView().addJavascriptInterface(new WidgetBridge(), "GradeBookWidgetNative");
        askNotificationPermission();
        requestTokenFromRuStore();
        //Приложение могли ОТКРЫТЬ нажатием на уведомление («холодный» старт).
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        //Приложение уже было открыто — нажатие приходит сюда, а не в onCreate.
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        String eventId = intent.getStringExtra(GradeBookPushService.EXTRA_EVENT_ID);
        if (eventId == null || eventId.isEmpty()) {
            return;
        }
        //Не зовём веб-слой, а откладываем: он мог ещё не загрузиться. Заберёт сам.
        prefs().edit().putString(KEY_PENDING_TAP, eventId).apply();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /**
     * Спросить токен устройства у RuStore напрямую.
     *
     * Почему не хватает `onNewToken` в сервисе: тот срабатывает, только когда токен
     * ВЫДАЛИ ИЛИ СМЕНИЛИ. Если сохранить его не удалось (или данные приложения
     * почистили), нового события можно ждать вечно — и уведомления не придут никогда,
     * без единой ошибки. Активный запрос при каждом запуске делает состояние
     * восстановимым: одного открытия приложения достаточно, чтобы всё починилось.
     *
     * Причину отказа записываем: на телефоне без RuStore/VK Push доставки не будет в
     * принципе, и человек должен видеть это в настройках, а не гадать.
     */
    private void requestTokenFromRuStore() {
        try {
            RuStorePushClient.INSTANCE.getToken()
                    .addOnSuccessListener(new OnSuccessListener<String>() {
                        @Override
                        public void onSuccess(String result) {
                            if (result == null || result.isEmpty()) {
                                prefs().edit().putString(KEY_LAST_ERROR,
                                        "RuStore не выдал токен устройства").apply();
                                return;
                            }
                            Log.i(TAG, "токен устройства получен");
                            prefs().edit().putString(KEY_TOKEN, result)
                                    .putString(KEY_LAST_ERROR, "").apply();
                        }
                    })
                    .addOnFailureListener(new OnFailureListener() {
                        @Override
                        public void onFailure(Throwable throwable) {
                            String why = throwable != null
                                    ? String.valueOf(throwable.getMessage()) : "";
                            Log.w(TAG, "токен не получен: " + why);
                            prefs().edit().putString(KEY_LAST_ERROR,
                                    why.isEmpty() ? "RuStore Push недоступен" : why).apply();
                        }
                    });
        } catch (Throwable e) {
            //Сюда попадаем, если SDK не инициализирован (нет project_id в сборке).
            //Пуши — дополнение: журнал обязан работать и без них.
            Log.w(TAG, "RuStore Push недоступен: " + e);
            prefs().edit().putString(KEY_LAST_ERROR, "RuStore Push не инициализирован").apply();
        }
    }

    /** Android 13+ требует явного разрешения на показ уведомлений. */
    private void askNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return;   //на более старых версиях разрешение выдаётся при установке
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                    this, new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    REQ_NOTIFICATIONS);
        }
    }

    /** Объект, видимый из JS как window.GradeBookPushNative. */
    public class PushBridge {

        /**
         * Токен устройства. Пустая строка — токена ещё нет (первый запуск до ответа
         * RuStore, или на телефоне нет RuStore вовсе). Веб-слой тогда ничего не шлёт
         * и повторит попытку — он опрашивает мост несколько раз после старта.
         */
        @JavascriptInterface
        public String getToken() {
            return prefs().getString(KEY_TOKEN, "");
        }

        /**
         * Забрать нажатое уведомление ("" — нажатий не было).
         *
         * ЗАБРАТЬ, а не подсмотреть: событие снимается тем же действием, иначе один
         * тап срабатывал бы при каждом открытии приложения.
         */
        @JavascriptInterface
        public String consumeTap() {
            SharedPreferences p = prefs();
            String id = p.getString(KEY_PENDING_TAP, "");
            if (!id.isEmpty()) {
                p.edit().remove(KEY_PENDING_TAP).apply();
            }
            return id;
        }

        /**
         * Состояние пушей для раздела «Настройки»: есть ли токен и почему нет.
         * Молчаливый отказ — худшее, что может случиться с уведомлениями: и человек, и
         * мы узнаём о нём только по отсутствию сообщений, то есть никогда.
         */
        @JavascriptInterface
        public String diagnostics() {
            SharedPreferences p = prefs();
            JSONObject out = new JSONObject();
            try {
                out.put("has_token", !p.getString(KEY_TOKEN, "").isEmpty());
                out.put("error", p.getString(KEY_LAST_ERROR, ""));
                out.put("permission", Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                        || ContextCompat.checkSelfPermission(MainActivity.this,
                                Manifest.permission.POST_NOTIFICATIONS)
                           == PackageManager.PERMISSION_GRANTED);
            } catch (Exception e) {
                return "{}";
            }
            return out.toString();
        }
    }

    /**
     * Объект, видимый из JS как window.GradeBookWidgetNative — мост к виджету
     * расписания на рабочем столе (см. web/src/services/scheduleWidget.js).
     *
     * ━━ ПОЧЕМУ СНИМОК КЛАДЁТ ВЕБ-СЛОЙ, А НЕ ВИДЖЕТ ХОДИТ САМ ━━
     * У виджета нет и не может быть долгоживущего доступа к серверу: токен в проекте
     * живёт жёстко 5 часов (§6), после чего нужен повторный вход. Виджет, работающий
     * первые пять часов после входа, а дальше показывающий ошибку, — хуже, чем виджет,
     * честно рисующий последний загруженный снимок. Расписание портала недельное и
     * меняется редко, а «какой сегодня день» и «какая пара идёт» считаются локально,
     * поэтому кэш остаётся верным неограниченно долго.
     *
     * Роль и группу тоже определяет веб-слой: развилка «студент видит свою группу,
     * преподаватель — свои пары» уже разобрана на сервере по роли токена, и вторая её
     * копия в нативном коде разъехалась бы с первой.
     */
    public class WidgetBridge {

        /**
         * Положить снимок расписания и перерисовать виджеты.
         *
         * JSON НЕ разбираем здесь: любой сбой разбора на UI-потоке — это подвисание
         * приложения ради виджета, которого может вообще не быть на рабочем столе.
         * Строка кладётся как есть, а разбирает её провайдер при отрисовке, где
         * повреждённый кэш безопасно вырождается в «данных нет».
         */
        @JavascriptInterface
        public void save(String json) {
            if (json == null || json.isEmpty()) {
                return;
            }
            getSharedPreferences(ScheduleWidgetData.PREFS, Context.MODE_PRIVATE)
                    .edit().putString(ScheduleWidgetData.KEY_SNAPSHOT, json).apply();
            ScheduleWidgetProvider.refreshAll(MainActivity.this);
        }

        /**
         * Забыть расписание — зовётся при выходе из аккаунта.
         *
         * Обязательно: на телефоне может войти другой человек (в колледже это норма),
         * и оставленный на рабочем столе виджет показывал бы группу предыдущего
         * владельца сессии. Это ровно та же граница, по которой при логауте
         * сбрасываются сторы мессенджера и Вектора.
         */
        @JavascriptInterface
        public void clear() {
            getSharedPreferences(ScheduleWidgetData.PREFS, Context.MODE_PRIVATE)
                    .edit().remove(ScheduleWidgetData.KEY_SNAPSHOT).apply();
            ScheduleWidgetProvider.refreshAll(MainActivity.this);
        }

        /**
         * Есть ли смысл собирать снимок: true, если виджет реально размещён на
         * рабочем столе. Веб-слой спрашивает это ПЕРЕД сериализацией — расписание
         * целиком весит десятки килобайт, и гонять их через мост на каждом заходе у
         * тех, кто виджет не ставил, незачем.
         */
        @JavascriptInterface
        public boolean isPlaced() {
            try {
                android.appwidget.AppWidgetManager mgr =
                        android.appwidget.AppWidgetManager.getInstance(MainActivity.this);
                int[] ids = mgr.getAppWidgetIds(new android.content.ComponentName(
                        MainActivity.this, ScheduleWidgetProvider.class));
                return ids != null && ids.length > 0;
            } catch (Throwable e) {
                return false;
            }
        }
    }
}
