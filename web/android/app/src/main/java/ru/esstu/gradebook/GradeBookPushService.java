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
 * Что приходит в сообщении. НИ БАЛЛА, НИ ПРЕДМЕТА, НИ ФИО — только заголовок
 * «Новая оценка» и служебный event_id. Так сделано намеренно: тело уведомления идёт
 * через серверы RuStore, то есть через третью сторону, а успеваемость студента —
 * персональные данные (152-ФЗ). Подробности приложение забирает у нашего сервера
 * по event_id уже после открытия.
 *
 * Токен устройства НЕ отправляется отсюда: у сервиса нет сессии пользователя, и он не
 * знает, кому телефон принадлежит сейчас. Токен подхватывает веб-слой через мост
 * (см. MainActivity) и шлёт на сервер вместе с авторизацией — так уведомления всегда
 * достаются последнему вошедшему аккаунту.
 */
public class GradeBookPushService extends RuStoreMessagingService {

    private static final String TAG = "GradeBookPush";
    private static final String CHANNEL_ID = "grades";
    /** Куда сложить event_id, чтобы MainActivity подхватил его при открытии. */
    public static final String EXTRA_EVENT_ID = "gb_event_id";

    @Override
    public void onNewToken(String token) {
        //Токен обновился (переустановка, чистка данных). Сохраняем локально — веб-слой
        //заберёт его при следующем запуске и подтвердит на сервере уже с авторизацией.
        Log.i(TAG, "получен новый токен устройства");
        getSharedPreferences("gb_push", Context.MODE_PRIVATE)
                .edit().putString("token", token).apply();
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        Map<String, String> data = message.getData();
        String eventId = data != null ? data.get("event_id") : null;

        String title = "Новая оценка";
        String body = "У вас новая оценка. Откройте журнал, чтобы посмотреть.";
        if (message.getNotification() != null) {
            if (message.getNotification().getTitle() != null) {
                title = message.getNotification().getTitle();
            }
            if (message.getNotification().getBody() != null) {
                body = message.getNotification().getBody();
            }
        }
        showNotification(title, body, eventId);
    }

    private void showNotification(String title, String body, String eventId) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) {
            return;
        }
        //Канал обязателен начиная с Android 8; создание идемпотентно.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Оценки", NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Уведомления о новых оценках в журнале");
            nm.createNotificationChannel(channel);
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

        Notification n = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build();
        nm.notify(requestCode, n);
    }
}
