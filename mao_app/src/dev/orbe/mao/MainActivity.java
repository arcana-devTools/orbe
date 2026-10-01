package dev.orbe.mao;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

public final class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);
        final EditText token = findViewById(R.id.token);
        final TextView estado = findViewById(R.id.estado);
        String salvo = getSharedPreferences("mao", MODE_PRIVATE).getString("token", "");
        if (salvo.length() > 0) token.setText(salvo);
        findViewById(R.id.ligar).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String bruto = token.getText().toString();
                String t = extrair(bruto);
                if (t.length() < 8) {
                    estado.setText("Cola o token ou a linha do comando.");
                    return;
                }
                getSharedPreferences("mao", MODE_PRIVATE).edit().putString("token", t).apply();
                if (Build.VERSION.SDK_INT >= 33) {
                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
                }
                Intent i = new Intent(MainActivity.this, MaoService.class);
                if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
                else startService(i);
                estado.setText("Mão ligada. O aviso fica na barra. Para a mão do Termux, senão as duas disputam a ordem.");
            }
        });
        findViewById(R.id.acesso).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
            }
        });
        findViewById(R.id.sobre).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                startActivity(i);
            }
        });
        findViewById(R.id.bateria).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:" + getPackageName()));
                try {
                    startActivity(i);
                } catch (Exception e) {
                    estado.setText("O Android não mostrou o aviso da bateria.");
                }
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        TextView estado = findViewById(R.id.estado);
        String extra = Olho.ligado() ? " Leitura da tela ligada." : " Leitura da tela desligada.";
        if (estado.getText() == null || estado.getText().length() < 8) {
            estado.setText("Parada." + extra);
        }
    }

    static String extrair(String bruto) {
        if (bruto == null) return "";
        String s = bruto.trim();
        int i = s.indexOf("--token ");
        if (i >= 0) {
            String resto = s.substring(i + 8).trim();
            int fim = resto.indexOf(' ');
            return fim < 0 ? resto : resto.substring(0, fim);
        }
        return s.split("\\s+")[0];
    }
}
