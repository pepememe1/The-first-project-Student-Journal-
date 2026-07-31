package ru.esstu.gradebook;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import java.util.Map;

import ru.rustore.sdk.pushclient.messaging.model.RemoteMessage;
import ru.rustore.sdk.pushclient.messaging.service.RuStoreMessagingService;

/**
 * Приём пуш-уведомлений RuStore.
 *
 * Что приходит в сообщении. НИ БАЛЛА, НИ ПРЕДМЕТА, НИ ФИО — только нейтральный
 * заголовок и служебный event_id. Так сделано намеренно: тело уведомления идёт через
 * серверы RuStore, то есть через третью сторону, а успеваемость студента —
 * персональные данные (152-ФЗ). Подробности приложение забирает у нашего сервера по
 * event_id уже после открытия.
 *
 * Токен устройства НЕ отправляется отсюда: у сервиса нет сессии пользователя, и он не
 * знает, кому телефон принадлежит сейчас. Токен подхватывает веб-слой через мост
 * (см. MainActivity) и шлёт на сервер вместе с авторизацией — так уведомления всегда
 * достаются последнему вошедшему аккаунту.
 */
public class GradeBookPushService extends RuStoreMessagingService {

    private static final String TAG = "GradeBookPush";
    /** Куда сложить event_id, чтобы MainActivity подхватил его при открытии. */
    public static final String EXTRA_EVENT_ID = "gb_event_id";

    @Override
    public void onNewToken(String token) {
        //Токен обновился (переустановка, чистка данных). Сохраняем локально — веб-слой
        //заберёт его при следующем запуске и подтвердит на сервере уже с авторизацией.
        //MainActivity дополнительно спрашивает токен сам: полагаться на одно это
        //событие нельзя — оно приходит ровно один раз и может быть пропущено.
        Log.i(TAG, "получен новый токен устройства");
        getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString(MainActivity.KEY_TOKEN, token)
                .putString(MainActivity.KEY_LAST_ERROR, "")
                .apply();
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        Map<String, String> data = message.getData();
        String eventId = data != null ? data.get("event_id") : null;
        String type = data != null ? data.get("type") : null;

        String title = "GradeBookAI";
        String body = "Есть новое событие. Откройте приложение, чтобы посмотреть.";
        if (message.getNotification() != null) {
            if (message.getNotification().getTitle() != null) {
                title = message.getNotification().getTitle();
            }
            if (message.getNotification().getBody() != null) {
                body = message.getNotification().getBody();
            }
        }
        showNotification(title, body, eventId, type);
    }

    /**
     * Канал уведомления по типу события.
     *
     * Зачем разные каналы, когда раньше был один общий «Оценки»: канал — это ЕДИНИЦА
     * управления уведомлениями в самой Android (звук, важность, полное отключение
     * долгим нажатием на уведомление). С одним каналом человек, которому надоели
     * сообщения из чата, мог отключить только всё сразу — вместе с оценками. Наши
     * настройки в приложении при этом никуда не деваются: они решают, отправлять ли
     * пуш вообще, а канал — как показать его на этом телефоне.
     */
    private static String channelId(String type) {
        if (type == null) {
            return "other";
        }
        switch (type) {
            case "grade":
            case "grade_changed":
                return "grades";
            case "homework":
                return "homework";
            case "schedule_changed":
                return "schedule";
            case "message":
                return "messages";
            case "event":
                return "events";
            case "reminder":
                return "reminders";
            default:
                return "other";
        }
    }

    private static String channelName(String id) {
        switch (id) {
            case "grades":
                return "Оценки";
            case "homework":
                return "Домашние задания";
            case "schedule":
                return "Расписание";
            case "messages":
                return "Сообщения";
            case "events":
                return "Мероприятия";
            case "reminders":
                return "Напоминания";
            default:
                return "Прочее";
        }
    }

    private void showNotification(String title, String body, String eventId, String type) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) {
            return;
        }
        String channel = channelId(type);
        //Канал обязателен начиная с Android 8; создание идемпотентно.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    channel, channelName(channel), NotificationManager.IMPORTANCE_DEFAULT);
            nm.createNotificationChannel(ch);
        }

        Intent intent = new Intent(this, MainActivity.class);
        //SINGLE_TOP + CLEAR_TOP: приложение уже открыто — переиспользуем экран, а не
        //плодим второй поверх первого (иначе кнопка «назад» уводит в старую копию).
        intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (eventId != null) {
            intent.putExtra(EXTRA_EVENT_ID, eventId);
        }
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;   //требование Android 12+
        }
        //requestCode делаем разным по событию: иначе PendingIntent переиспользуется и
        //второе уведомление открывало бы экран ПЕРВОГО.
        int requestCode = eventId != null ? eventId.hashCode() : 0;
        PendingIntent pi = PendingIntent.getActivity(this, requestCode, intent, flags);

        Notification n = new NotificationCompat.Builder(this, channel)
                .setSmallIcon(R.drawable.ic_stat_notify)
                .setContentTitle(title)
                .setContentText(body)
                //Тексты у нас длиннее одной строки («Не откладывайте: подойдите к
                //преподавателю…»), а обычный вид обрезает их многоточием.
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build();
        nm.notify(requestCode, n);
    }
}
