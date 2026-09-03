package vn.smarttkb.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
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
import android.webkit.ValueCallback;
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
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String SERVER_URL = BuildConfig.APP_BASE_URL;
    private static final String PREFS_NAME = "smart_tkb";
    private static final String PREF_MANAGED_SERVER_URL = "managed_server_url";
    private static final String PREF_LAST_WORKING_SERVER_URL = "last_working_server_url";
    private static final int STORAGE_PERMISSION_REQUEST = 41;
    private static final int FILE_CHOOSER_REQUEST = 42;

    private WebView webView;
    private ProgressBar progressBar;
    private LinearLayout errorPanel;
    private PendingDownload pendingDownload;
    private ValueCallback<Uri[]> filePathCallback;
    private boolean mainFrameLoadFailed;
    private volatile String currentServerUrl = SERVER_URL;

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
        settings.setAllowContentAccess(true);
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

            @Override
            public boolean onShowFileChooser(
                    WebView webView,
                    ValueCallback<Uri[]> callback,
                    FileChooserParams fileChooserParams
            ) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                Intent intent = fileChooserParams.createIntent();
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                if (fileChooserParams.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                    return true;
                } catch (ActivityNotFoundException exception) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, "Không tìm thấy ứng dụng chọn tệp.", Toast.LENGTH_LONG).show();
                    return false;
                }
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
                    String workingUrl = normalizeHttpsBaseUrl(currentServerUrl);
                    if (workingUrl != null) {
                        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                                .edit()
                                .putString(PREF_LAST_WORKING_SERVER_URL, workingUrl)
                                .apply();
                    }
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
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_REQUEST) {
            Uri[] results = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    int count = data.getClipData().getItemCount();
                    results = new Uri[count];
                    for (int index = 0; index < count; index++) {
                        results[index] = data.getClipData().getItemAt(index).getUri();
                    }
                } else if (data.getData() != null) {
                    results = new Uri[]{data.getData()};
                }
            }
            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
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

        SharedPreferences preferences = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        String cachedUrl = normalizeHttpsBaseUrl(preferences.getString(PREF_MANAGED_SERVER_URL, ""));
        String lastWorkingUrl = normalizeHttpsBaseUrl(preferences.getString(PREF_LAST_WORKING_SERVER_URL, ""));
        String buildUrl = normalizeHttpsBaseUrl(SERVER_URL);
        currentServerUrl = cachedUrl != null ? cachedUrl : (lastWorkingUrl != null ? lastWorkingUrl : SERVER_URL);
        webView.loadUrl(currentServerUrl);
        refreshManagedServerUrl(buildUrl, lastWorkingUrl);
    }

    private void refreshManagedServerUrl(String buildUrl, String lastWorkingUrl) {
        new Thread(() -> {
            String resolvedUrl = resolveManagedServerUrl(currentServerUrl, lastWorkingUrl, buildUrl);
            if (resolvedUrl == null) return;

            getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                    .edit()
                    .putString(PREF_MANAGED_SERVER_URL, resolvedUrl)
                    .apply();

            runOnUiThread(() -> {
                if (isFinishing() || resolvedUrl.equals(currentServerUrl)) return;
                currentServerUrl = resolvedUrl;
                mainFrameLoadFailed = false;
                errorPanel.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);
                webView.loadUrl(resolvedUrl);
            });
        }, "smart-tkb-mobile-config").start();
    }

    private String resolveManagedServerUrl(String currentUrl, String lastWorkingUrl, String buildUrl) {
        String[] candidates = new String[]{currentUrl, lastWorkingUrl, buildUrl};
        for (int index = 0; index < candidates.length; index++) {
            String candidate = normalizeHttpsBaseUrl(candidates[index]);
            if (candidate == null) continue;
            boolean duplicate = false;
            for (int previous = 0; previous < index; previous++) {
                String previousCandidate = normalizeHttpsBaseUrl(candidates[previous]);
                if (candidate.equals(previousCandidate)) {
                    duplicate = true;
                    break;
                }
            }
            if (duplicate) continue;

            String advertisedUrl = fetchManagedServerUrl(candidate);
            if (advertisedUrl == null) continue;
            if (candidate.equals(advertisedUrl) || fetchManagedServerUrl(advertisedUrl) != null) {
                return advertisedUrl;
            }

            // Server nguồn vẫn hoạt động nhưng URL mới đang lỗi: giữ server
            // đang dùng được thay vì ghi đè cache bằng một địa chỉ chết.
            return candidate;
        }
        return null;
    }

    private String fetchManagedServerUrl(String baseUrl) {
        String normalizedBaseUrl = normalizeHttpsBaseUrl(baseUrl);
        if (normalizedBaseUrl == null) return null;
        HttpURLConnection connection = null;
        try {
            URL configUrl = new URL(normalizedBaseUrl + "/api/mobile/config");
            connection = (HttpURLConnection) configUrl.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(2500);
            connection.setReadTimeout(2500);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-cache");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) return null;

            StringBuilder body = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    connection.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) body.append(line);
            }
            JSONObject response = new JSONObject(body.toString());
            return normalizeHttpsBaseUrl(response.optString("apk_base_url", ""));
        } catch (Exception ignored) {
            return null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String normalizeHttpsBaseUrl(String rawUrl) {
        if (rawUrl == null) return null;
        String value = rawUrl.trim();
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        if (value.isEmpty()) return null;
        for (int index = 0; index < value.length(); index++) {
            if (Character.isWhitespace(value.charAt(index))) return null;
        }
        try {
            URI uri = new URI(value);
            int port = uri.getPort();
            if (!"https".equalsIgnoreCase(uri.getScheme())
                    || uri.getHost() == null
                    || uri.getUserInfo() != null
                    || uri.getRawQuery() != null
                    || uri.getFragment() != null
                    || port > 65535) {
                return null;
            }
            String path = uri.getPath();
            if (path != null && !path.isEmpty() && !"/".equals(path)) return null;
            String host = uri.getHost();
            String authority = host.contains(":")
                    ? (host.startsWith("[") ? host : "[" + host + "]")
                    : host;
            if (port >= 0) authority += ":" + port;
            return "https://" + authority;
        } catch (Exception ignored) {
            return null;
        }
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
        if (filePathCallback != null) {
            filePathCallback.onReceiveValue(null);
            filePathCallback = null;
        }
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
