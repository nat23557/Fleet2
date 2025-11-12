import React, { useCallback, useMemo, useRef, useState, useEffect } from 'react';
import { SafeAreaView, View, Text, TouchableOpacity, ActivityIndicator, Platform, BackHandler, StatusBar, Linking, Alert } from 'react-native';
import { WebView } from 'react-native-webview';

const DEFAULT_URL = 'http://localhost:8000/';

export default function App() {
  const webRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [canGoBack, setCanGoBack] = useState(false);
  const [canGoForward, setCanGoForward] = useState(false);
  const [currentUrl, setCurrentUrl] = useState('');

  // Configure the base URL via env: EXPO_PUBLIC_WEB_BASE_URL
  const baseUrl = useMemo(() => {
    const envUrl = process.env.EXPO_PUBLIC_WEB_BASE_URL;
    return (envUrl && envUrl.trim().length > 0) ? envUrl : DEFAULT_URL;
  }, []);

  // Android hardware back button -> navigate back in webview if possible
  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canGoBack && webRef.current) {
        webRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [canGoBack]);

  const onNavChange = useCallback((navState) => {
    setCanGoBack(navState.canGoBack);
    setCanGoForward(navState.canGoForward);
    setCurrentUrl(navState.url);
  }, []);

  // Open external links in system browser; keep same-origin in app
  const onShouldStart = useCallback((req) => {
    try {
      const targetUrl = new URL(req.url);
      const base = new URL(baseUrl);
      const sameHost = targetUrl.host === base.host;
      if (!sameHost && (req.navigationType !== 'other' || targetUrl.protocol.startsWith('http'))) {
        Linking.openURL(req.url);
        return false;
      }
      // allow in-app for same host or non-http schemes we want to handle
      return true;
    } catch (e) {
      return true;
    }
  }, [baseUrl]);

  const reload = useCallback(() => {
    webRef.current?.reload();
  }, []);

  const goHome = useCallback(() => {
    webRef.current?.loadUrl?.(baseUrl);
    // Fallback if loadUrl not available
    if (webRef.current?.injectJavaScript) {
      webRef.current.injectJavaScript(`window.location.href = '${baseUrl}'; true;`);
    }
  }, [baseUrl]);

  const onError = useCallback(() => {
    setLoading(false);
    Alert.alert('Connection error', 'Unable to load the app. Check your network and try again.', [
      { text: 'Retry', onPress: reload },
      { text: 'Cancel', style: 'cancel' }
    ]);
  }, [reload]);

  const userAgent = useMemo(() => {
    const base = Platform.select({ ios: 'iOS', android: 'Android', default: 'Web' });
    return `FleetApp/0.1 (${base})`;
  }, []);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#ffffff' }}>
      <StatusBar barStyle={Platform.OS === 'ios' ? 'dark-content' : 'light-content'} />
      <View style={{ flex: 1 }}>
        <WebView
          ref={webRef}
          source={{ uri: baseUrl }}
          userAgent={userAgent}
          onLoadStart={() => setLoading(true)}
          onLoadEnd={() => setLoading(false)}
          onError={onError}
          onNavigationStateChange={onNavChange}
          onShouldStartLoadWithRequest={onShouldStart}
          javaScriptEnabled
          domStorageEnabled
          allowFileAccess
          allowUniversalAccessFromFileURLs
          setSupportMultipleWindows={false}
          originWhitelist={["*"]}
          startInLoadingState
          mixedContentMode="always"
          cacheEnabled
          style={{ flex: 1 }}
        />

        {/* Loading overlay */}
        {loading && (
          <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 48, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.2)' }}>
            <ActivityIndicator size="large" color="#0d6efd" />
          </View>
        )}

        {/* Simple bottom toolbar */}
        <View style={{ height: 48, flexDirection: 'row', borderTopWidth: 1, borderTopColor: '#eee', backgroundColor: '#fafafa' }}>
          <ToolbarButton label="Back" disabled={!canGoBack} onPress={() => webRef.current?.goBack()} />
          <ToolbarButton label="Forward" disabled={!canGoForward} onPress={() => webRef.current?.goForward()} />
          <ToolbarButton label="Refresh" onPress={reload} />
          <ToolbarButton label="Home" onPress={goHome} />
        </View>
      </View>
    </SafeAreaView>
  );
}

function ToolbarButton({ label, onPress, disabled }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      style={{ flex: 1, alignItems: 'center', justifyContent: 'center', opacity: disabled ? 0.4 : 1 }}
    >
      <Text style={{ fontSize: 14, color: '#0d6efd', fontWeight: '600' }}>{label}</Text>
    </TouchableOpacity>
  );
}

