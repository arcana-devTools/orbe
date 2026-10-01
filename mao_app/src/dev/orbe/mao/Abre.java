package dev.orbe.mao;

import android.app.ActivityOptions;
import android.content.Context;
import android.content.Intent;
import android.graphics.Rect;
import android.util.DisplayMetrics;
import android.view.WindowManager;

final class Abre {
    static final class Resultado {
        final boolean ok;
        final String msg;
        Resultado(boolean ok, String msg) {
            this.ok = ok;
            this.msg = msg;
        }
    }

    static Resultado app(Context ctx, String alvo) {
        String pkg = Apps.pacote(alvo);
        if (pkg.length() == 0) return new Resultado(false, "não conheço esse app");
        Intent intent = ctx.getPackageManager().getLaunchIntentForPackage(pkg);
        if (intent == null) return new Resultado(false, "app não instalado");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Rect caixa = caixa(ctx);
        try {
            ActivityOptions op = ActivityOptions.makeBasic();
            op.setLaunchBounds(caixa);
            ctx.startActivity(intent, op.toBundle());
            return new Resultado(true, "pedi " + alvo + " na janela pequena");
        } catch (Exception e) {
            try {
                ctx.startActivity(intent);
                return new Resultado(true, "pedi " + alvo + " em tela cheia");
            } catch (Exception e2) {
                return new Resultado(false, "o Android não deixou abrir");
            }
        }
    }

    static Resultado url(Context ctx, String url) {
        if (url == null || !url.startsWith("https://")) return new Resultado(false, "url recusada");
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            intent.setPackage("com.android.chrome");
            ctx.startActivity(intent);
            return new Resultado(true, "pedi o Chrome");
        } catch (Exception e) {
            return new Resultado(false, "não abri o Chrome");
        }
    }

    private static Rect caixa(Context ctx) {
        DisplayMetrics m = new DisplayMetrics();
        WindowManager wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        wm.getDefaultDisplay().getRealMetrics(m);
        int w = m.widthPixels;
        int h = m.heightPixels;
        int esquerda = w / 2;
        int topo = h / 8;
        int direita = w - (w / 18);
        int baixo = h / 2;
        return new Rect(esquerda, topo, direita, baixo);
    }

    private Abre() {}
}
