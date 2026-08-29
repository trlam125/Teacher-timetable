package vn.smarttkb.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {
    // Khi URL ngrok thay đổi, chỉ cần sửa hằng số này rồi build lại APK.
    private static final String SERVER_URL = "https://yahoo-speech-radiation.ngrok-free.dev";
    private static final int STORAGE_PERMISSION_REQUEST = 41;

    private WebView webView;
    private ProgressBar progressBar;
    private LinearLayout errorPanel;
    private PendingDownload pendingDownload;
    private boolean mainFrameLoadFailed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createInterface();
        loadHome();
    }

    private void createInterface() {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(Color.WHITE);

        FrameLayout content = new FrameLayout(this);
        webView = new WebView(this);
        configureWebView();
        content.addView(webView, matchParent());

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        content.addView(progressBar, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        errorPanel = createErrorPanel();
        errorPanel.setVisibility(View.GONE);
        content.addView(errorPanel, matchParent());

        page.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(page);
    }

    @SuppressLint("SetJavaScriptEnabled") // Giao diện Smart TKB cần JavaScript để gọi API và dựng thời khóa biểu.
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        settings.setTextZoom(100);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, true);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                progressBar.setProgress(progress);
                progressBar.setVisibility(progress < 100 ? View.VISIBLE : View.GONE);
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                super.onPageStarted(view, url, favicon);
                mainFrameLoadFailed = false;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme();
                if ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme)) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {
                    Toast.makeText(MainActivity.this, "Không có ứng dụng mở liên kết này.", Toast.LENGTH_SHORT).show();
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                injectWebViewCompatibilityCss(view);
                injectTouchDragSupport(view);
                if (!mainFrameLoadFailed) {
                    errorPanel.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                }
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                super.onReceivedError(view, request, error);
                if (request.isForMainFrame()) {
                    mainFrameLoadFailed = true;
                    showConnectionError();
                }
            }
        });

        webView.setDownloadListener(createDownloadListener());
    }

    private void injectWebViewCompatibilityCss(WebView view) {
        String script = "(function(){"
                + "var id='smart-tkb-android-fixes';"
                + "if(document.getElementById(id))return;"
                + "var style=document.createElement('style');style.id=id;"
                + "style.textContent='.appbar,.top{backdrop-filter:none!important;"
                + "-webkit-backdrop-filter:none!important;}"
                + "[data-android-drag-value]{-webkit-user-select:none!important;user-select:none!important;}"
                + ".android-touch-ghost{position:fixed!important;z-index:2147483647!important;"
                + "pointer-events:none!important;margin:0!important;opacity:.9!important;"
                + "transform:scale(1.04)!important;box-shadow:0 18px 45px rgba(15,23,42,.35)!important;}"
                + ".android-touch-drop-target{box-shadow:inset 0 0 0 4px #06b6d4!important;"
                + "background-color:#cffafe!important;}';"
                + "document.head.appendChild(style);"
                + "})();";
        view.evaluateJavascript(script, null);
    }

    private void injectTouchDragSupport(WebView view) {
        StringBuilder script = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                getAssets().open("android-touch-drag.js"), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                script.append(line).append('\n');
            }
            view.evaluateJavascript(script.toString(), null);
        } catch (IOException exception) {
            Toast.makeText(this, "Không thể bật kéo thả cảm ứng.", Toast.LENGTH_LONG).show();
        }
    }

    private DownloadListener createDownloadListener() {
        return (url, userAgent, contentDisposition, mimeType, contentLength) -> {
            pendingDownload = new PendingDownload(url, userAgent, contentDisposition, mimeType);
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
                    && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_PERMISSION_REQUEST);
                return;
            }
            enqueueDownload(pendingDownload);
        };
    }

    private void enqueueDownload(PendingDownload download) {
        try {
            String fileName = URLUtil.guessFileName(download.url, download.contentDisposition, download.mimeType);
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(download.url));
            request.setMimeType(download.mimeType);
            request.addRequestHeader("User-Agent", download.userAgent);
            String cookie = CookieManager.getInstance().getCookie(download.url);
            if (cookie != null) request.addRequestHeader("Cookie", cookie);
            request.setTitle(fileName);
            request.setDescription("Đang tải từ Smart TKB");
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
            DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            manager.enqueue(request);
            Toast.makeText(this, "Đang tải xuống: " + fileName, Toast.LENGTH_LONG).show();
        } catch (Exception exception) {
            Toast.makeText(this, "Không thể tải tệp: " + exception.getMessage(), Toast.LENGTH_LONG).show();
        } finally {
            pendingDownload = null;
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == STORAGE_PERMISSION_REQUEST && pendingDownload != null) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                enqueueDownload(pendingDownload);
            } else {
                Toast.makeText(this, "Cần quyền lưu trữ để tải tệp.", Toast.LENGTH_LONG).show();
                pendingDownload = null;
            }
        }
    }

    private LinearLayout createErrorPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setPadding(dp(28), dp(28), dp(28), dp(28));
        panel.setBackgroundColor(Color.WHITE);

        TextView heading = new TextView(this);
        heading.setText(R.string.connection_error_title);
        heading.setTextSize(21);
        heading.setTextColor(Color.rgb(30, 41, 59));
        heading.setGravity(Gravity.CENTER);
        panel.addView(heading);

        TextView message = new TextView(this);
        message.setText(R.string.connection_error_message);
        message.setTextSize(15);
        message.setTextColor(Color.rgb(100, 116, 139));
        message.setGravity(Gravity.CENTER);
        message.setPadding(0, dp(12), 0, dp(18));
        panel.addView(message);

        Button retry = new Button(this);
        retry.setText(R.string.retry);
        retry.setOnClickListener(view -> loadHome());
        panel.addView(retry);

        return panel;
    }

    private void showConnectionError() {
        progressBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        errorPanel.setVisibility(View.VISIBLE);
    }

    private void loadHome() {
        if (!hasNetwork()) {
            showConnectionError();
            return;
        }
        errorPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(SERVER_URL);
    }

    private boolean hasNetwork() {
        ConnectivityManager manager = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null) return false;
        NetworkCapabilities capabilities = manager.getNetworkCapabilities(manager.getActiveNetwork());
        return capabilities != null && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private FrameLayout.LayoutParams matchParent() {
        return new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private static class PendingDownload {
        final String url;
        final String userAgent;
        final String contentDisposition;
        final String mimeType;

        PendingDownload(String url, String userAgent, String contentDisposition, String mimeType) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
        }
    }
}
