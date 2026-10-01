package dev.orbe.mao;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public final class MaoService extends Service {
    static final String BASE = "https://orbe-xfzn.onrender.com";
    private volatile boolean vivo = true;
    private Thread fio;

    @Override
    public void onCreate() {
        super.onCreate();
        canal();
        Notification n = aviso("Mão ligada. Esperando ordem.");
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(7, n, 1073741824);
        } else {
            startForeground(7, n);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (fio == null) {
            fio = new Thread(new Runnable() {
                @Override
                public void run() {
                    loop();
                }
            });
            fio.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        vivo = false;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void loop() {
        while (vivo) {
            try {
                String token = getSharedPreferences("mao", MODE_PRIVATE).getString("token", "");
                if (token.length() < 8) {
                    avisoAtual("Falta o token.");
                    dormir(5000);
                    continue;
                }
                String corpo = get(BASE + "/api/mao/fila?aparelho=celular", token, 40000);
                JSONObject j = new JSONObject(corpo);
                if (j.isNull("comando")) continue;
                JSONObject cmd = j.getJSONObject("comando");
                String id = cmd.optString("id");
                String acao = cmd.optString("acao");
                String alvo = cmd.optString("alvo");
                JSONObject extra = cmd.optJSONObject("extra");
                Resultado r = executar(acao, alvo, extra);
                avisoAtual(r.resumo);
                postResultado(token, id, r);
            } catch (Exception e) {
                avisoAtual("sem ligação");
                dormir(5000);
            }
        }
    }

    private static final class Resultado {
        boolean ok;
        String resumo;
        byte[] imagem;
        Resultado(boolean ok, String resumo, byte[] imagem) {
            this.ok = ok;
            this.resumo = resumo;
            this.imagem = imagem;
        }
    }

    private Resultado executar(String acao, String alvo, JSONObject extra) {
        if ("abrir_app".equals(acao)) {
            Abre.Resultado r = Abre.app(this, alvo);
            dormir(1200);
            String tela = Olho.ler();
            String msg = r.msg;
            if (tela.length() > 0) msg = r.msg + ". " + primeira(tela);
            return new Resultado(r.ok, corta(msg), tela.length() == 0 ? null : TelaTexto.png(tela));
        }
        if ("abrir_url".equals(acao)) {
            Abre.Resultado r = Abre.url(this, alvo);
            return new Resultado(r.ok, r.msg, null);
        }
        if ("print".equals(acao)) {
            if (!Olho.ligado()) return new Resultado(false, "liga a leitura da tela", null);
            String tela = Olho.ler();
            if (tela.length() == 0) return new Resultado(false, "não vi a tela da frente", null);
            return new Resultado(true, "li a tela da frente", TelaTexto.png(tela));
        }
        if ("clicar".equals(acao)) {
            int x = extra == null ? -1 : extra.optInt("x", -1);
            int y = extra == null ? -1 : extra.optInt("y", -1);
            String msg = Olho.clicarPonto(x, y);
            return new Resultado("cliquei".equals(msg), msg, null);
        }
        if ("digitar".equals(acao)) {
            String msg = Olho.digitar(alvo);
            return new Resultado("digitei".equals(msg), msg, null);
        }
        if ("tecla".equals(acao)) {
            return new Resultado(false, "tecla ainda não", null);
        }
        return new Resultado(false, "ação desconhecida", null);
    }

    private void postResultado(String token, String id, Resultado r) throws Exception {
        JSONObject corpo = new JSONObject();
        corpo.put("id", id);
        corpo.put("ok", r.ok);
        corpo.put("resumo", r.resumo == null ? "" : r.resumo);
        corpo.put("aparelho", "celular");
        if (r.imagem != null && r.imagem.length > 0 && r.imagem.length < 1800000) {
            corpo.put("imagem", Base64.getEncoder().encodeToString(r.imagem));
        }
        post(BASE + "/api/mao/resultado", token, corpo.toString());
    }

    private static String get(String url, String token, int timeout) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod("GET");
        c.setConnectTimeout(timeout);
        c.setReadTimeout(timeout);
        c.setRequestProperty("x-orbe-mao", token);
        c.setRequestProperty("User-Agent", "orbe-mao-app");
        return ler(c);
    }

    private static void post(String url, String token, String json) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(40000);
        c.setReadTimeout(40000);
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json");
        c.setRequestProperty("x-orbe-mao", token);
        c.setRequestProperty("User-Agent", "orbe-mao-app");
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        OutputStream out = c.getOutputStream();
        out.write(bytes);
        out.close();
        ler(c);
    }

    private static String ler(HttpURLConnection c) throws Exception {
        InputStream in;
        try {
            in = c.getInputStream();
        } catch (Exception e) {
            in = c.getErrorStream();
        }
        if (in == null) return "{}";
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] tmp = new byte[4096];
        int n;
        while ((n = in.read(tmp)) >= 0) buf.write(tmp, 0, n);
        in.close();
        return buf.toString("UTF-8");
    }

    private void canal() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationChannel ch = new NotificationChannel("mao", "Mão do Orbe", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Aviso de que a mão está ligada.");
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.createNotificationChannel(ch);
    }

    private Notification aviso(String texto) {
        Intent i = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, i, PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, "mao")
                : new Notification.Builder(this);
        return b.setSmallIcon(android.R.drawable.ic_menu_send)
                .setContentTitle("Mão do Orbe")
                .setContentText(texto)
                .setOngoing(true)
                .setContentIntent(pi)
                .build();
    }

    private void avisoAtual(String texto) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(7, aviso(corta(texto)));
    }

    private static String corta(String s) {
        if (s == null) return "";
        return s.length() > 140 ? s.substring(0, 140) : s;
    }

    private static String primeira(String tela) {
        int n = tela.indexOf('\n');
        String l = n < 0 ? tela : tela.substring(0, n);
        return l.length() > 80 ? l.substring(0, 80) : l;
    }

    private static void dormir(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }
}
