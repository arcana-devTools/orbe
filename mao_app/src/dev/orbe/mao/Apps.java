package dev.orbe.mao;

import java.util.HashMap;

final class Apps {
    private static final HashMap<String, String> NOMES = new HashMap<String, String>();

    static {
        NOMES.put("whatsapp", "com.whatsapp");
        NOMES.put("instagram", "com.instagram.android");
        NOMES.put("telegram", "org.telegram.messenger");
        NOMES.put("gmail", "com.google.android.gm");
        NOMES.put("chrome", "com.android.chrome");
        NOMES.put("youtube", "com.google.android.youtube");
        NOMES.put("mapas", "com.google.android.apps.maps");
        NOMES.put("camera", "com.android.camera2");
        NOMES.put("shopee", "com.shopee.br");
        NOMES.put("mercadolivre", "com.mercadolibre");
    }

    static String pacote(String alvo) {
        if (alvo == null) return "";
        String limpo = alvo.trim().toLowerCase();
        String conhecido = NOMES.get(limpo);
        if (conhecido != null) return conhecido;
        if (limpo.indexOf('.') > 0 && limpo.indexOf(' ') < 0) return limpo;
        return "";
    }

    private Apps() {}
}
