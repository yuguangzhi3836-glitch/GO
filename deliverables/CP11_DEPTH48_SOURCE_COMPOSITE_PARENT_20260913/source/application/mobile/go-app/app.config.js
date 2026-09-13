// Build-time API binding. Local development retains the existing loopback API.
module.exports = ({ config }) => {
  const profile = process.env.EAS_BUILD_PROFILE || '';
  const environment = process.env.EXPO_PUBLIC_ENV || '';
  const externalBuild = ['preview', 'production'].includes(profile) ||
    ['staging', 'production'].includes(environment);
  const supplied = process.env.EXPO_PUBLIC_API_URL || process.env.EXPO_PUBLIC_API_BASE_URL;
  if (externalBuild && !supplied) throw new Error('GO_BUILD_API_BASE_URL_REQUIRED');
  const apiBaseUrl = supplied || config.extra?.apiBaseUrl || 'http://localhost:8000';
  let url;
  try { url = new URL(apiBaseUrl); } catch { throw new Error('GO_BUILD_API_BASE_URL_INVALID'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error('GO_BUILD_API_BASE_URL_INVALID');
  const host = url.hostname.toLowerCase();
  if (externalBuild && (url.protocol !== 'https:' || host === 'localhost' ||
      host.endsWith('.localhost') || host === '[::1]' || /^127\./.test(host) ||
      host === '0.0.0.0' || host === 'invalid' || host.endsWith('.invalid')))
    throw new Error('GO_BUILD_API_BASE_URL_NOT_DEPLOYABLE');
  return { ...config, version: '1.1.0', runtimeVersion: {policy: 'appVersion'},
    updates: {fallbackToCacheTimeout: 0},
    extra: { ...config.extra, environment: environment || 'development',
      apiBaseUrl: url.href.replace(/\/$/, ''),
      eas: {projectId: process.env.EXPO_PUBLIC_EAS_PROJECT_ID || 'REPLACE_WITH_EAS_PROJECT_ID'} },
    ios: {...config.ios, buildNumber: process.env.IOS_BUILD_NUMBER || '1'},
    android: {...config.android, versionCode: Number(process.env.ANDROID_VERSION_CODE || 1)} };
};
