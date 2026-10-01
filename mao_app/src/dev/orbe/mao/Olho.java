package dev.orbe.mao;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;

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

    static String ler() {
        Olho o = ativo;
        if (o == null) return "";
        AccessibilityNodeInfo raiz = o.getRootInActiveWindow();
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
        AccessibilityNodeInfo raiz = o.getRootInActiveWindow();
        if (raiz == null) return "não vi a tela";
        try {
            if (temSenha(raiz)) return "tela de login, não mexo";
            AccessibilityNodeInfo achou = acharTexto(raiz, texto.toLowerCase(Locale.ROOT));
            if (achou == null) return "não achei esse botão";
            if (proibido(textoDe(achou))) {
                achou.recycle();
                return "não mexo nisso";
            }
            boolean ok = achou.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            if (!ok && achou.getParent() != null) ok = achou.getParent().performAction(AccessibilityNodeInfo.ACTION_CLICK);
            achou.recycle();
            return ok ? "cliquei" : "o botão não aceitou";
        } finally {
            raiz.recycle();
        }
    }

    static String clicarPonto(int x, int y) {
        Olho o = ativo;
        if (o == null) return "leitura da tela desligada";
        AccessibilityNodeInfo raiz = o.getRootInActiveWindow();
        if (raiz == null) return "não vi a tela";
        try {
            if (temSenha(raiz)) return "tela de login, não mexo";
            AccessibilityNodeInfo achou = acharPonto(raiz, x, y);
            if (achou == null) return "não há botão nesse ponto";
            if (achou.isPassword() || proibido(textoDe(achou))) {
                achou.recycle();
                return "não mexo nisso";
            }
            boolean ok = achou.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            achou.recycle();
            return ok ? "cliquei" : "o botão não aceitou";
        } finally {
            raiz.recycle();
        }
    }

    static String digitar(String texto) {
        if (texto == null || texto.length() == 0 || texto.length() > 500) return "texto recusado";
        Olho o = ativo;
        if (o == null) return "leitura da tela desligada";
        AccessibilityNodeInfo raiz = o.getRootInActiveWindow();
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
                if (s.length() > 0) sb.append(s).append('\n');
            }
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo f = n.getChild(i);
            if (f == null) continue;
            juntar(f, sb, fundo + 1);
            f.recycle();
        }
    }

    private static AccessibilityNodeInfo acharTexto(AccessibilityNodeInfo n, String needle) {
        if (n == null) return null;
        String s = textoDe(n).toLowerCase(Locale.ROOT);
        if (s.length() > 0 && s.contains(needle) && (n.isClickable() || n.isEnabled())) {
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
                || s.contains("aceitar termo") || s.contains("aceito os termos")
                || s.contains("concordo");
    }
}
