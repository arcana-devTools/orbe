package dev.orbe.mao;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import java.util.List;

import java.util.ArrayList;
import java.util.Locale;

public final class Olho extends AccessibilityService {
    static volatile Olho ativo;

    @Override
    public void onServiceConnected() {
        ativo = this;
    }

    @Override
    public void onDestroy() {
        if (ativo == this) ativo = null;
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(android.view.accessibility.AccessibilityEvent event) {
    }

    @Override
    public void onInterrupt() {
    }

    static boolean ligado() {
        return ativo != null;
    }

    static AccessibilityNodeInfo raizAlvo(Olho o) {
        if (o == null) return null;
        AccessibilityNodeInfo melhor = null;
        int scoreMelhor = -1;
        try {
            List<AccessibilityWindowInfo> wins = o.getWindows();
            if (wins != null) {
                for (int i = 0; i < wins.size(); i++) {
                    AccessibilityWindowInfo w = wins.get(i);
                    if (w == null) continue;
                    if (w.getType() != AccessibilityWindowInfo.TYPE_APPLICATION) continue;
                    AccessibilityNodeInfo r = w.getRoot();
                    if (r == null) continue;
                    String pkg = r.getPackageName() == null ? "" : r.getPackageName().toString();
                    if (pkg.startsWith("com.android.systemui")
                            || pkg.startsWith("com.samsung.android.app.cocktailbarservice")
                            || "dev.orbe.mao".equals(pkg)) {
                        r.recycle();
                        continue;
                    }
                    Rect b = new Rect();
                    r.getBoundsInScreen(b);
                    if (b.width() < 200 || b.height() < 200) {
                        r.recycle();
                        continue;
                    }
                    int score = w.getLayer() * 100000 + Math.min(b.width() * b.height() / 1000, 20000);
                    if (w.isFocused() || w.isActive()) score += 500000;
                    if (score > scoreMelhor) {
                        if (melhor != null) melhor.recycle();
                        melhor = r;
                        scoreMelhor = score;
                    } else {
                        r.recycle();
                    }
                }
            }
        } catch (Exception ignored) {
        }
        if (melhor != null) return melhor;
        return o.getRootInActiveWindow();
    }

    static String ler() {
        Olho o = ativo;
        if (o == null) return "";
        AccessibilityNodeInfo raiz = raizAlvo(o);
        if (raiz == null) return "";
        StringBuilder sb = new StringBuilder();
        try {
            CharSequence pkg = raiz.getPackageName();
            if (pkg != null) sb.append("pacote ").append(pkg).append('\n');
            Rect b = new Rect();
            raiz.getBoundsInScreen(b);
            sb.append("janela ").append(b.width()).append("x").append(b.height()).append('\n');
            if (temSenha(raiz)) sb.append("tela de login, não mexo\n");
            juntar(raiz, sb, 0);
        } finally {
            raiz.recycle();
        }
        String t = sb.toString().trim();
        if (t.length() > 4000) t = t.substring(0, 4000);
        return t;
    }

    static String clicarTexto(String texto) {
        if (proibido(texto)) return "não mexo nisso";
        Olho o = ativo;
        if (o == null) return "leitura da tela desligada";
        AccessibilityNodeInfo raiz = raizAlvo(o);
        if (raiz == null) return "não vi a tela";
        try {
            if (temSenha(raiz)) return "tela de login, não mexo";
            Rect janela = new Rect();
            raiz.getBoundsInScreen(janela);
            AccessibilityNodeInfo achou = acharVisivel(raiz, texto.toLowerCase(Locale.ROOT), janela);
            if (achou == null) return "não achei esse botão";
            if (proibido(textoDe(achou))) {
                achou.recycle();
                return "não mexo nisso";
            }
            String antes = marca(raiz);
            Rect alvo = boundsUteis(achou);
            boolean tocou = alvo != null && gesto(alvo.centerX(), alvo.centerY());
            if (!tocou) tocou = tocar(achou);
            achou.recycle();
            if (!tocou) return "o botão não aceitou";
            try {
                Thread.sleep(1200);
            } catch (InterruptedException ignored) {
            }
            String depois = marcaFrente();
            if (depois.length() > 0 && depois.equals(antes)) return "toquei, a tela não mudou";
            return "cliquei";
        } finally {
            raiz.recycle();
        }
    }

    static String clicarPonto(int x, int y) {
        Olho o = ativo;
        if (o == null) return "leitura da tela desligada";
        AccessibilityNodeInfo raiz = raizAlvo(o);
        if (raiz == null) return "não vi a tela";
        try {
            if (temSenha(raiz)) return "tela de login, não mexo";
            AccessibilityNodeInfo achou = acharPonto(raiz, x, y);
            if (achou == null) return "não há botão nesse ponto";
            if (achou.isPassword() || proibido(textoDe(achou))) {
                achou.recycle();
                return "não mexo nisso";
            }
            Rect alvo = boundsUteis(achou);
            String antes = marca(raiz);
            boolean ok = alvo != null && gesto(alvo.centerX(), alvo.centerY());
            if (!ok) ok = achou.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            achou.recycle();
            if (!ok) return "o botão não aceitou";
            try {
                Thread.sleep(1200);
            } catch (InterruptedException ignored) {
            }
            String depois = marcaFrente();
            if (depois.length() > 0 && depois.equals(antes)) return "toquei, a tela não mudou";
            return "cliquei";
        } finally {
            raiz.recycle();
        }
    }

    static String digitar(String texto) {
        if (texto == null || texto.length() == 0 || texto.length() > 500) return "texto recusado";
        Olho o = ativo;
        if (o == null) return "leitura da tela desligada";
        AccessibilityNodeInfo raiz = raizAlvo(o);
        if (raiz == null) return "não vi a tela";
        try {
            if (temSenha(raiz)) return "tela de login, não mexo";
            AccessibilityNodeInfo foco = raiz.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            if (foco == null) return "não há campo";
            if (foco.isPassword()) {
                foco.recycle();
                return "não digito senha";
            }
            android.os.Bundle args = new android.os.Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, texto);
            boolean ok = foco.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            foco.recycle();
            return ok ? "digitei" : "o campo não aceitou";
        } finally {
            raiz.recycle();
        }
    }

    private static boolean temSenha(AccessibilityNodeInfo n) {
        if (n == null) return false;
        if (n.isPassword()) return true;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            boolean achou = temSenha(f);
            f.recycle();
            if (achou) return true;
        }
        return false;
    }

    private static void juntar(AccessibilityNodeInfo n, StringBuilder sb, int fundo) {
        if (n == null || fundo > 30 || sb.length() > 4000) return;
        if (!n.isPassword()) {
            CharSequence t = n.getText();
            if (t == null || t.length() == 0) t = n.getContentDescription();
            if (t != null && t.length() > 0) {
                String s = t.toString().replace('\n', ' ').trim();
                if (s.length() > 0) {
                    Rect r = new Rect();
                    n.getBoundsInScreen(r);
                    sb.append(s).append(" @").append(r.centerX()).append(",").append(r.centerY()).append('\n');
                }
            }
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            juntar(f, sb, fundo + 1);
            f.recycle();
        }
    }

    private static boolean tocar(AccessibilityNodeInfo n) {
        AccessibilityNodeInfo cur = n;
        for (int i = 0; i < 8 && cur != null; i++) {
            if (!proibido(textoDe(cur))) {
                if (cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true;
            }
            AccessibilityNodeInfo pai = cur.getParent();
            if (cur != n) cur.recycle();
            cur = pai;
        }
        if (cur != null && cur != n) cur.recycle();
        return false;
    }

    private static AccessibilityNodeInfo acharVisivel(AccessibilityNodeInfo n, String needle, Rect janela) {
        if (n == null) return null;
        String s = textoDe(n).toLowerCase(Locale.ROOT);
        if (s.length() > 0 && s.contains(needle) && !proibido(s)) {
            Rect r = new Rect();
            n.getBoundsInScreen(r);
            if (r.width() > 4 && r.height() > 4 && janela.contains(r.centerX(), r.centerY())) {
                return AccessibilityNodeInfo.obtain(n);
            }
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            AccessibilityNodeInfo achou = acharVisivel(f, needle, janela);
            f.recycle();
            if (achou != null) return achou;
        }
        return null;
    }

    private static Rect boundsUteis(AccessibilityNodeInfo n) {
        AccessibilityNodeInfo cur = n;
        for (int i = 0; i < 6 && cur != null; i++) {
            Rect r = new Rect();
            cur.getBoundsInScreen(r);
            if (r.width() > 8 && r.height() > 8 && r.centerX() > 0 && r.centerY() > 0) {
                if (cur != n) cur.recycle();
                return r;
            }
            AccessibilityNodeInfo pai = cur.getParent();
            if (cur != n) cur.recycle();
            cur = pai;
        }
        if (cur != null && cur != n) cur.recycle();
        return null;
    }

    private static boolean gesto(int x, int y) {
        Olho o = ativo;
        if (o == null || x < 1 || y < 1) return false;
        Path path = new Path();
        path.moveTo(x, y);
        path.lineTo(x + 1, y + 1);
        GestureDescription.StrokeDescription stroke = new GestureDescription.StrokeDescription(path, 0, 120);
        GestureDescription g = new GestureDescription.Builder().addStroke(stroke).build();
        final boolean[] feito = new boolean[] {false};
        final Object trava = new Object();
        boolean enviou;
        try {
            enviou = o.dispatchGesture(g, new GestureResultCallback() {
                @Override
                public void onCompleted(GestureDescription gestureDescription) {
                    synchronized (trava) {
                        feito[0] = true;
                        trava.notifyAll();
                    }
                }

                @Override
                public void onCancelled(GestureDescription gestureDescription) {
                    synchronized (trava) {
                        trava.notifyAll();
                    }
                }
            }, null);
        } catch (Exception ignored) {
            return false;
        }
        if (!enviou) return false;
        synchronized (trava) {
            try {
                trava.wait(1800);
            } catch (InterruptedException ignored) {
            }
        }
        return feito[0];
    }

    private static String marca(AccessibilityNodeInfo n) {
        StringBuilder sb = new StringBuilder();
        marcaEm(n, sb, 0);
        String t = sb.toString();
        return t.length() > 1500 ? t.substring(0, 1500) : t;
    }

    private static void marcaEm(AccessibilityNodeInfo n, StringBuilder sb, int fundo) {
        if (n == null || fundo > 30 || sb.length() > 1500) return;
        if (!n.isPassword()) {
            CharSequence t = n.getText();
            if (t == null || t.length() == 0) t = n.getContentDescription();
            if (t != null && t.length() > 0) sb.append(t.toString().replace('\n', ' ').trim()).append('|');
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            marcaEm(f, sb, fundo + 1);
            f.recycle();
        }
    }

    private static String marcaFrente() {
        Olho o = ativo;
        if (o == null) return "";
        AccessibilityNodeInfo raiz = raizAlvo(o);
        if (raiz == null) return "";
        try {
            return marca(raiz);
        } finally {
            raiz.recycle();
        }
    }

    private static AccessibilityNodeInfo acharTexto(AccessibilityNodeInfo n, String needle) {
        if (n == null) return null;
        String s = textoDe(n).toLowerCase(Locale.ROOT);
        if (s.length() > 0 && s.contains(needle) && !proibido(s)) {
            return AccessibilityNodeInfo.obtain(n);
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            AccessibilityNodeInfo achou = acharTexto(f, needle);
            f.recycle();
            if (achou != null) return achou;
        }
        return null;
    }

    private static AccessibilityNodeInfo acharPonto(AccessibilityNodeInfo n, int x, int y) {
        if (n == null) return null;
        Rect r = new Rect();
        n.getBoundsInScreen(r);
        if (!r.contains(x, y)) return null;
        for (int i = n.getChildCount() - 1; i >= 0; i--) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            AccessibilityNodeInfo achou = acharPonto(f, x, y);
            f.recycle();
            if (achou != null) return achou;
        }
        if (n.isClickable()) return AccessibilityNodeInfo.obtain(n);
        return null;
    }

    private static String textoDe(AccessibilityNodeInfo n) {
        CharSequence t = n.getText();
        if (t == null || t.length() == 0) t = n.getContentDescription();
        return t == null ? "" : t.toString();
    }

    private static boolean proibido(String texto) {
        if (texto == null) return false;
        String s = texto.toLowerCase(Locale.ROOT);
        return s.contains("senha") || s.contains("login") || s.contains("captcha")
                || s.contains("não sou um robô") || s.contains("nao sou um robo")
                || s.contains("termo") || s.contains("concordo");
    }
}
