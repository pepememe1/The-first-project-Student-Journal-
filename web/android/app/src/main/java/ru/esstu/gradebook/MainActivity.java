package ru.esstu.gradebook;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.webkit.JavascriptInterface;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.BridgeActivity;

/**
 * Точка входа приложения + МОСТ между нативными пушами и веб-слоем.
 *
 * Зачем мост, а не плагин Capacitor: нужны ровно две вещи — отдать веб-слою токен
 * устройства и сообщить, что уведомление нажали. Полноценный плагин ради двух функций
 * был бы лишним слоем, который придётся сопровождать при каждом обновлении Capacitor.
 *
 * Токен НЕ отправляется на сервер отсюда. Здесь нет сессии пользователя, а телефон
 * должен принадлежать ПОСЛЕДНЕМУ вошедшему аккаунту — иначе студент, вошедший после
 * друга, получал бы чужие уведомления. Поэтому токен забирает веб-слой и шлёт его
 * вместе с авторизацией (см. web/src/services/push.js).
 */
public class MainActivity extends BridgeActivity {

    private static final String TAG = "GradeBookPush";
    private static final int REQ_NOTIFICATIONS = 4201;

    /** event_id из уведомления, нажатого ДО того, как веб-слой успел подписаться. */
    private String pendingEventId = null;
    /** Готов ли веб-слой принимать нажатия. */
    private boolean tapCallbackReady = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        registerBridge();
        askNotificationPermission();
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
        //Веб-слой мог ещё не загрузиться — придерживаем событие до его готовности.
        pendingEventId = eventId;
        deliverPendingTap();
    }

    private void deliverPendingTap() {
        if (pendingEventId == null || !tapCallbackReady || getBridge() == null) {
            return;
        }
        final String eventId = pendingEventId;
        pendingEventId = null;
        runOnUiThread(() -> {
            try {
                //Экранируем спецсимволы: event_id это uuid, но полагаться на форму
                //данных, пришедших извне, нельзя — это прямой путь к инъекции в JS.
                String safe = eventId.replace("\\", "\\\\").replace("'", "\\'");
                getBridge().getWebView().evaluateJavascript(
                        "window.__gbPushTap && window.__gbPushTap('" + safe + "')", null);
            } catch (Exception e) {
                Log.w(TAG, "не удалось передать нажатие в веб-слой: " + e);
            }
        });
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

    private void registerBridge() {
        getBridge().getWebView().addJavascriptInterface(new PushBridge(), "GradeBookPushNative");
        //Тонкая обёртка над нативным объектом: превращает синхронный вызов в promise и
        //хранит колбэк нажатия. Веб-слой знает только про window.GradeBookPush —
        //нативные детали за ним не видны.
        getBridge().getWebView().post(() -> getBridge().getWebView().evaluateJavascript(
                "window.GradeBookPush = {"
                + "  getToken: () => Promise.resolve(window.GradeBookPushNative.getToken()),"
                + "  onTap: (cb) => { window.__gbPushTap = cb;"
                + "                   window.GradeBookPushNative.tapReady(); }"
                + "};", null));
    }

    /** Объект, видимый из JS как window.GradeBookPushNative. */
    public class PushBridge {

        /**
         * Токен устройства, сохранённый сервисом при выдаче/обновлении.
         * Пустая строка — токена ещё нет (первый запуск до ответа RuStore). Веб-слой
         * тогда ничего не шлёт и повторит попытку при следующем запуске.
         */
        @JavascriptInterface
        public String getToken() {
            return getSharedPreferences("gb_push", Context.MODE_PRIVATE)
                    .getString("token", "");
        }

        /** Веб-слой сообщил, что готов принимать нажатия. */
        @JavascriptInterface
        public void tapReady() {
            tapCallbackReady = true;
            deliverPendingTap();   //нажатие могло прийти ДО готовности — отдаём сейчас
        }
    }
}
