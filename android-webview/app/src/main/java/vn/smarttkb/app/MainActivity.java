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
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Message;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
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
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final int STORAGE_PERMISSION_REQUEST = 41;
    private static final int FILE_CHOOSER_REQUEST = 42;
    private static final String SERVER_URL = normalizeServerUrl(BuildConfig.SERVER_URL);
    private static final Uri SERVER_URI = Uri.parse(SERVER_URL);
    private static final Pattern UTF8_FILENAME_PATTERN = Pattern.compile(
            "filename\\*=UTF-8''([^;]+)", Pattern.CASE_INSENSITIVE
    );
    private static final Pattern FILENAME_PATTERN = Pattern.compile(
            "filename=\\\"?([^\\\";]+)\\\"?", Pattern.CASE_INSENSITIVE
    );

    private WebView webView;
    private ProgressBar progressBar;
    private LinearLayout errorPanel;
    private TextView errorMessage;
    private PendingDownload pendingDownload;
    private ValueCallback<Uri[]> fileChooserCallback;
    private boolean mainFrameLoadFailed;
    private String lastFailedUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createInterface();
        if (savedInstanceState != null && webView.restoreState(savedInstanceState) != null) {
            return;
        }
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
        progressBar.setVisibility(View.GONE);
        content.addView(progressBar, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(3)
        ));

        errorPanel = createErrorPanel();
        errorPanel.setVisibility(View.GONE);
        content.addView(errorPanel, matchParent());

        page.addView(content, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1
        ));
        setContentView(page);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        settings.setTextZoom(100);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setGeolocationEnabled(false);
        settings.setUserAgentString(
                settings.getUserAgentString() + " SmartTKBAndroid/" + BuildConfig.VERSION_NAME
        );

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.setSafeBrowsingEnabled(true);
        }
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);

        webView.setWebChromeClient(createWebChromeClient());
        webView.setWebViewClient(createWebViewClient());
        webView.setDownloadListener(createDownloadListener());
    }

    @SuppressLint("SetJavaScriptEnabled")
    private WebChromeClient createWebChromeClient() {
        return new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                progressBar.setProgress(progress);
                progressBar.setVisibility(progress < 100 ? View.VISIBLE : View.GONE);
            }

            @Override
            public boolean onShowFileChooser(
                    WebView view,
                    ValueCallback<Uri[]> filePathCallback,
                    FileChooserParams fileChooserParams
            ) {
                String currentUrl = view.getUrl();
                if (currentUrl == null || !isInternalUri(Uri.parse(currentUrl))) {
                    filePathCallback.onReceiveValue(null);
                    return false;
                }

                if (fileChooserCallback != null) {
                    fileChooserCallback.onReceiveValue(null);
                }
                fileChooserCallback = filePathCallback;

                try {
                    Intent chooserIntent = fileChooserParams.createIntent();
                    chooserIntent.addCategory(Intent.CATEGORY_OPENABLE);
                    startActivityForResult(chooserIntent, FILE_CHOOSER_REQUEST);
                    return true;
                } catch (Exception exception) {
                    fileChooserCallback.onReceiveValue(null);
                    fileChooserCallback = null;
                    Toast.makeText(
                            MainActivity.this,
                            "Không tìm thấy ứng dụng chọn tệp.",
                            Toast.LENGTH_LONG
                    ).show();
                    return false;
                }
            }

            @Override
            public boolean onCreateWindow(
                    WebView view,
                    boolean isDialog,
                    boolean isUserGesture,
                    Message resultMsg
            ) {
                if (!isUserGesture) {
                    return false;
                }

                WebView popup = new WebView(MainActivity.this);
                WebSettings popupSettings = popup.getSettings();
                popupSettings.setJavaScriptEnabled(true);
                popupSettings.setDomStorageEnabled(false);
                popupSettings.setAllowFileAccess(false);
                popupSettings.setAllowContentAccess(false);
                popupSettings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

                popup.setWebViewClient(new WebViewClient() {
                    private boolean handled;

                    private void handlePopupUrl(String url) {
                        if (handled || url == null || url.trim().isEmpty() || "about:blank".equals(url)) {
                            return;
                        }
                        handled = true;
                        Uri uri = Uri.parse(url);
                        if (isInternalUri(uri)) {
                            loadInternalUrl(uri.toString());
                        } else {
                            openExternalUri(uri);
                        }
                        popup.stopLoading();
                        popup.destroy();
                    }

                    @Override
                    public void onPageStarted(WebView popupView, String url, Bitmap favicon) {
                        super.onPageStarted(popupView, url, favicon);
                        handlePopupUrl(url);
                    }

                    @Override
                    public boolean shouldOverrideUrlLoading(
                            WebView popupView,
                            WebResourceRequest request
                    ) {
                        handlePopupUrl(request.getUrl().toString());
                        return true;
                    }
                });

                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(popup);
                resultMsg.sendToTarget();
                return true;
            }
        };
    }

    private WebViewClient createWebViewClient() {
        return new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                super.onPageStarted(view, url, favicon);
                mainFrameLoadFailed = false;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isInternalUri(uri)) {
                    return false;
                }
                openExternalUri(uri);
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if (isInternalUri(Uri.parse(url))) {
                    injectWebViewCompatibilityCss(view);
                    injectTouchDragSupport(view);
                }
                if (!mainFrameLoadFailed) {
                    errorPanel.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                    lastFailedUrl = null;
                }
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceError error
            ) {
                super.onReceivedError(view, request, error);
                if (request.isForMainFrame()) {
                    mainFrameLoadFailed = true;
                    lastFailedUrl = request.getUrl().toString();
                    showConnectionError(R.string.connection_error_message);
                }
            }

            @Override
            public void onReceivedHttpError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceResponse errorResponse
            ) {
                super.onReceivedHttpError(view, request, errorResponse);
                if (request.isForMainFrame() && errorResponse.getStatusCode() >= 500) {
                    mainFrameLoadFailed = true;
                    lastFailedUrl = request.getUrl().toString();
                    showConnectionError(R.string.server_error_message);
                }
            }

            @Override
            public void onReceivedSslError(
                    WebView view,
                    SslErrorHandler handler,
                    SslError error
            ) {
                handler.cancel();
                mainFrameLoadFailed = true;
                lastFailedUrl = view.getUrl();
                showConnectionError(R.string.ssl_error_message);
            }
        };
    }

    private void injectWebViewCompatibilityCss(WebView view) {
        String script = "(function(){"
                + "var id='smart-tkb-android-fixes';"
                + "if(document.getElementById(id))return;"
                + "var style=document.createElement('style');style.id=id;"
                + "style.textContent='[data-android-drag-value]{-webkit-user-select:none!important;user-select:none!important;-webkit-touch-callout:none!important;}"
                + ".android-touch-ghost{position:fixed!important;z-index:2147483647!important;pointer-events:none!important;margin:0!important;opacity:.9!important;transform:scale(1.04)!important;box-shadow:0 18px 45px rgba(15,23,42,.35)!important;}"
                + ".android-touch-drop-target{outline:4px solid #06b6d4!important;outline-offset:-4px!important;}';"
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
            Uri uri = Uri.parse(url);
            if (!isInternalUri(uri)) {
                openExternalUri(uri);
                return;
            }

            pendingDownload = new PendingDownload(
                    url,
                    userAgent,
                    contentDisposition,
                    mimeType,
                    webView.getUrl()
            );
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
                    && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                        new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE},
                        STORAGE_PERMISSION_REQUEST
                );
                return;
            }
            enqueueDownload(pendingDownload);
        };
    }

    private void enqueueDownload(PendingDownload download) {
        try {
            String fileName = resolveFileName(download);
            String mimeType = download.mimeType == null || download.mimeType.trim().isEmpty()
                    ? "application/octet-stream"
                    : download.mimeType;

            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(download.url));
            request.setMimeType(mimeType);
            if (download.userAgent != null && !download.userAgent.trim().isEmpty()) {
                request.addRequestHeader("User-Agent", download.userAgent);
            }
            String cookie = CookieManager.getInstance().getCookie(download.url);
            if (cookie != null && !cookie.trim().isEmpty()) {
                request.addRequestHeader("Cookie", cookie);
            }
            if (download.referer != null && !download.referer.trim().isEmpty()) {
                request.addRequestHeader("Referer", download.referer);
            }
            request.addRequestHeader("ngrok-skip-browser-warning", "true");
            request.setTitle(fileName);
            request.setDescription("Đang tải từ Smart TKB");
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(false);
            request.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            );
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);

            DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            if (manager == null) {
                throw new IllegalStateException("DownloadManager không khả dụng");
            }
            manager.enqueue(request);
            Toast.makeText(this, "Đang tải xuống: " + fileName, Toast.LENGTH_LONG).show();
        } catch (Exception exception) {
            Toast.makeText(
                    this,
                    "Không thể tải tệp: " + exception.getMessage(),
                    Toast.LENGTH_LONG
            ).show();
        } finally {
            pendingDownload = null;
        }
    }

    private String resolveFileName(PendingDownload download) {
        String disposition = download.contentDisposition == null ? "" : download.contentDisposition;
        Matcher utf8Matcher = UTF8_FILENAME_PATTERN.matcher(disposition);
        if (utf8Matcher.find()) {
            try {
                return sanitizeFileName(URLDecoder.decode(
                        utf8Matcher.group(1), StandardCharsets.UTF_8.name()
                ));
            } catch (Exception ignored) {
                // Tiếp tục dùng tên dự phòng phía dưới.
            }
        }

        Matcher filenameMatcher = FILENAME_PATTERN.matcher(disposition);
        if (filenameMatcher.find()) {
            return sanitizeFileName(filenameMatcher.group(1).trim());
        }

        return sanitizeFileName(URLUtil.guessFileName(
                download.url,
                download.contentDisposition,
                download.mimeType
        ));
    }

    private String sanitizeFileName(String fileName) {
        String safeName = fileName == null ? "tai-xuong" : fileName.trim();
        safeName = safeName.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_");
        safeName = safeName.replaceAll("[. ]+$", "");
        return safeName.trim().isEmpty() ? "tai-xuong" : safeName;
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == STORAGE_PERMISSION_REQUEST && pendingDownload != null) {
            if (grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                enqueueDownload(pendingDownload);
            } else {
                Toast.makeText(
                        this,
                        "Cần quyền lưu trữ để tải tệp.",
                        Toast.LENGTH_LONG
                ).show();
                pendingDownload = null;
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST || fileChooserCallback == null) {
            return;
        }

        Uri[] selected = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
        fileChooserCallback.onReceiveValue(filterSelectedUris(selected));
        fileChooserCallback = null;
    }

    private Uri[] filterSelectedUris(Uri[] selected) {
        if (selected == null || selected.length == 0) {
            return null;
        }
        ArrayList<Uri> accepted = new ArrayList<>();
        for (Uri uri : selected) {
            if (uri != null && "content".equalsIgnoreCase(uri.getScheme())) {
                accepted.add(uri);
            }
        }
        return accepted.isEmpty() ? null : accepted.toArray(new Uri[0]);
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

        errorMessage = new TextView(this);
        errorMessage.setText(R.string.connection_error_message);
        errorMessage.setTextSize(15);
        errorMessage.setTextColor(Color.rgb(100, 116, 139));
        errorMessage.setGravity(Gravity.CENTER);
        errorMessage.setPadding(0, dp(12), 0, dp(18));
        panel.addView(errorMessage);

        Button retry = new Button(this);
        retry.setText(R.string.retry);
        retry.setOnClickListener(view -> retryConnection());
        panel.addView(retry);

        return panel;
    }

    private void showConnectionError(int messageResource) {
        progressBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        errorMessage.setText(messageResource);
        errorPanel.setVisibility(View.VISIBLE);
    }

    private void retryConnection() {
        if (!hasNetwork()) {
            showConnectionError(R.string.network_error_message);
            return;
        }
        String target = lastFailedUrl;
        lastFailedUrl = null;
        loadInternalUrl(target == null || target.trim().isEmpty() ? SERVER_URL : target);
    }

    private void loadHome() {
        if (!isServerUrlValid()) {
            showConnectionError(R.string.invalid_server_url_message);
            return;
        }
        if (!hasNetwork()) {
            showConnectionError(R.string.network_error_message);
            return;
        }
        loadInternalUrl(SERVER_URL);
    }

    private void loadInternalUrl(String url) {
        Uri uri = Uri.parse(url);
        if (!isInternalUri(uri)) {
            openExternalUri(uri);
            return;
        }
        errorPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(url, defaultRequestHeaders());
    }

    private Map<String, String> defaultRequestHeaders() {
        Map<String, String> headers = new HashMap<>();
        headers.put("ngrok-skip-browser-warning", "true");
        return headers;
    }

    private boolean hasNetwork() {
        ConnectivityManager manager = (ConnectivityManager) getSystemService(
                Context.CONNECTIVITY_SERVICE
        );
        if (manager == null || manager.getActiveNetwork() == null) {
            return false;
        }
        NetworkCapabilities capabilities = manager.getNetworkCapabilities(
                manager.getActiveNetwork()
        );
        return capabilities != null
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private boolean isServerUrlValid() {
        return "https".equalsIgnoreCase(SERVER_URI.getScheme())
                && SERVER_URI.getHost() != null
                && !SERVER_URI.getHost().trim().isEmpty();
    }

    private boolean isInternalUri(Uri uri) {
        if (!isServerUrlValid() || uri == null) {
            return false;
        }
        return "https".equalsIgnoreCase(uri.getScheme())
                && SERVER_URI.getHost().equalsIgnoreCase(uri.getHost())
                && effectivePort(SERVER_URI) == effectivePort(uri);
    }

    private int effectivePort(Uri uri) {
        if (uri.getPort() >= 0) {
            return uri.getPort();
        }
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    private void openExternalUri(Uri uri) {
        if (uri == null || uri.getScheme() == null) {
            Toast.makeText(this, "Liên kết không hợp lệ.", Toast.LENGTH_SHORT).show();
            return;
        }

        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        if ("javascript".equals(scheme) || "file".equals(scheme) || "content".equals(scheme)) {
            Toast.makeText(this, "Liên kết này đã bị chặn.", Toast.LENGTH_SHORT).show();
            return;
        }

        try {
            Intent intent;
            if ("intent".equals(scheme)) {
                intent = Intent.parseUri(uri.toString(), Intent.URI_INTENT_SCHEME);
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
                intent.setComponent(null);
                intent.setSelector(null);
            } else {
                intent = new Intent(Intent.ACTION_VIEW, uri);
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
            }
            startActivity(intent);
        } catch (Exception ignored) {
            Toast.makeText(
                    this,
                    "Không có ứng dụng mở liên kết này.",
                    Toast.LENGTH_SHORT
            ).show();
        }
    }

    private static String normalizeServerUrl(String url) {
        if (url == null) {
            return "";
        }
        return url.trim().replaceAll("/+$", "");
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onPause() {
        webView.onPause();
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
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
        if (fileChooserCallback != null) {
            fileChooserCallback.onReceiveValue(null);
            fileChooserCallback = null;
        }
        if (webView != null) {
            webView.stopLoading();
            webView.loadUrl("about:blank");
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.removeAllViews();
            webView.destroy();
        }
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private FrameLayout.LayoutParams matchParent() {
        return new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        );
    }

    private static class PendingDownload {
        final String url;
        final String userAgent;
        final String contentDisposition;
        final String mimeType;
        final String referer;

        PendingDownload(
                String url,
                String userAgent,
                String contentDisposition,
                String mimeType,
                String referer
        ) {
            this.url = url;
            this.userAgent = userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType;
            this.referer = referer;
        }
    }
}
