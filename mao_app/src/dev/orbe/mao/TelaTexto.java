package dev.orbe.mao;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;

import java.io.ByteArrayOutputStream;

final class TelaTexto {
    static byte[] png(String texto) {
        String[] linhas = (texto == null ? "" : texto).split("\n");
        if (linhas.length > 80) {
            String[] corte = new String[80];
            System.arraycopy(linhas, 0, corte, 0, 80);
            linhas = corte;
        }
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(Color.BLACK);
        p.setTextSize(28f);
        int largura = 900;
        int altura = Math.max(200, 40 + linhas.length * 36);
        Bitmap bmp = Bitmap.createBitmap(largura, altura, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bmp);
        c.drawColor(Color.WHITE);
        float y = 36f;
        for (int i = 0; i < linhas.length; i++) {
            String linha = linhas[i];
            if (linha.length() > 70) linha = linha.substring(0, 70);
            c.drawText(linha, 16f, y, p);
            y += 36f;
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        bmp.compress(Bitmap.CompressFormat.PNG, 100, out);
        bmp.recycle();
        return out.toByteArray();
    }

    private TelaTexto() {}
}
