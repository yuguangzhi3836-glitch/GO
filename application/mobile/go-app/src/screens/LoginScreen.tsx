import React, {useState} from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import {GO, screen} from '../design';
import {Brand, Btn} from '../components/GO';
import {useAuth} from '../auth/AuthContext';
import {register as apiRegister} from '../api/client';

const TERMS = {
  consumer_service_terms: '2026-08-25-v1',
  privacy_policy: '2026-08-25-v1',
} as const;

type Mode = 'login' | 'register';

function errorMessage(error: unknown) {
  const code = error instanceof Error ? error.message : 'UNKNOWN_ERROR';
  const messages: Record<string, string> = {
    EMAIL_ALREADY_REGISTERED: '这个邮箱已经注册，请直接登录。',
    CONSUMER_TERMS_ACCEPTANCE_REQUIRED: '请先阅读并同意服务条款与隐私政策。',
    CONSUMER_TERMS_VERSION_MISMATCH: '条款版本已更新，请返回后重新确认。',
    INVALID_REGISTRATION_RESPONSE: '服务器已收到注册请求，但返回内容不完整。请尝试使用该邮箱登录。',
    NETWORK_RESULT_UNKNOWN: '网络中断，暂时无法确认注册是否完成。请先尝试登录，避免重复注册。',
    NETWORK_REQUEST_FAILED: '无法连接服务器，请检查网络后重试。',
    NETWORK_OFFLINE: '当前设备处于离线状态，请联网后重试。',
    SESSION_EXPIRED: '登录状态已过期，请重新登录。',
    INVALID_CREDENTIALS: '邮箱或密码不正确。',
  };
  return messages[code] || `操作失败（${code}），请稍后重试。`;
}

function Input({
  label,
  value,
  onChangeText,
  placeholder,
  secureTextEntry = false,
  keyboardType = 'default',
  autoCapitalize = 'sentences',
  textContentType,
  autoComplete,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  secureTextEntry?: boolean;
  keyboardType?: 'default' | 'email-address';
  autoCapitalize?: 'none' | 'sentences';
  textContentType?: 'emailAddress' | 'newPassword' | 'password' | 'name';
  autoComplete?: 'email' | 'new-password' | 'password' | 'name';
}) {
  return (
    <View style={{marginTop: 12}}>
      <Text style={{fontSize: 12, fontWeight: '500', color: GO.slate, marginBottom: 7}}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor="rgba(7,27,85,0.40)"
        secureTextEntry={secureTextEntry}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        textContentType={textContentType}
        autoComplete={autoComplete}
        style={screen.input}
      />
    </View>
  );
}

export default function Login() {
  const auth = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const registering = mode === 'register';

  const submit = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      Alert.alert('邮箱格式不正确', '请输入有效的邮箱地址。');
      return;
    }
    if (!password) {
      Alert.alert('请输入密码', '密码不能为空。');
      return;
    }

    if (!registering) {
      setBusy(true);
      try {
        await auth.login(normalizedEmail, password);
      } catch (error) {
        Alert.alert('登录失败', errorMessage(error));
      } finally {
        setBusy(false);
      }
      return;
    }

    if (password.length < 10) {
      Alert.alert('密码长度不足', '密码至少需要 10 个字符。');
      return;
    }
    if (password !== confirmPassword) {
      Alert.alert('两次密码不一致', '请重新确认密码。');
      return;
    }
    if (!acceptedTerms) {
      Alert.alert('需要确认条款', '注册前请阅读并勾选同意服务条款与隐私政策。');
      return;
    }

    setBusy(true);
    try {
      await apiRegister({
        email: normalizedEmail,
        password,
        display_name: displayName.trim() || undefined,
        accepted_terms: true,
        term_versions: TERMS,
      });
    } catch (error) {
      Alert.alert('注册失败', errorMessage(error));
      setBusy(false);
      return;
    }

    try {
      await auth.login(normalizedEmail, password);
    } catch (error) {
      Alert.alert('账号已创建', `自动登录没有完成：${errorMessage(error)}\n\n请返回登录页面，使用刚创建的邮箱和密码登录。`);
      setMode('login');
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode(registering ? 'login' : 'register');
    setAcceptedTerms(false);
    setPassword('');
    setConfirmPassword('');
  };

  return (
    <KeyboardAvoidingView
      style={{flex: 1, backgroundColor: GO.ivory}}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{flexGrow: 1, justifyContent: 'center', padding: 24, paddingBottom: 36}}
        keyboardShouldPersistTaps="handled">
        <Brand />
        <Text style={[screen.h1, {marginTop: 28}]}>{registering ? '创建 GO ID' : '欢迎回到 GO'}</Text>
        <Text style={[screen.sub, {marginTop: 8}]}>
          {registering
            ? '创建账号后即可管理旅行、支付方式与真实入住评价。'
            : '登录 GO ID，继续管理你的旅行、支付方式与真实入住评价。'}
        </Text>

        <View style={[screen.card, {marginTop: 28}]}>
          {registering && (
            <Input
              label="昵称（选填）"
              placeholder="你希望别人如何称呼你"
              value={displayName}
              onChangeText={setDisplayName}
              textContentType="name"
              autoComplete="name"
            />
          )}
          <Input
            label="邮箱"
            placeholder="name@example.com"
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
            textContentType="emailAddress"
            autoComplete="email"
          />
          <Input
            label="密码"
            placeholder={registering ? '至少 10 个字符' : '输入密码'}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            textContentType={registering ? 'newPassword' : 'password'}
            autoComplete={registering ? 'new-password' : 'password'}
          />
          {registering && (
            <Input
              label="确认密码"
              placeholder="再次输入密码"
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              secureTextEntry
              autoCapitalize="none"
              textContentType="newPassword"
              autoComplete="new-password"
            />
          )}

          {registering && (
            <Pressable
              accessibilityRole="checkbox"
              accessibilityState={{checked: acceptedTerms}}
              onPress={() => setAcceptedTerms(value => !value)}
              style={{flexDirection: 'row', alignItems: 'flex-start', marginTop: 18, paddingVertical: 8}}>
              <View style={{
                width: 22,
                height: 22,
                borderRadius: 5,
                borderWidth: 1,
                borderColor: acceptedTerms ? GO.blue : 'rgba(7,27,85,0.32)',
                backgroundColor: acceptedTerms ? GO.blue : GO.white,
                alignItems: 'center',
                justifyContent: 'center',
                marginRight: 10,
              }}>
                {acceptedTerms && <Text style={{color: GO.white, fontSize: 15, fontWeight: '700'}}>✓</Text>}
              </View>
              <Text style={[screen.sub, {flex: 1, lineHeight: 20}]}>
                我已阅读并同意 GO 服务条款（{TERMS.consumer_service_terms}）和隐私政策（{TERMS.privacy_policy}）。
              </Text>
            </Pressable>
          )}

          <Btn
            title={busy ? (registering ? '正在创建账号…' : '正在登录…') : registering ? '同意并创建账号' : '登录'}
            disabled={busy}
            onPress={submit}
          />
          <Btn
            title={registering ? '已有 GO ID？返回登录' : '创建 GO ID'}
            secondary
            disabled={busy}
            onPress={switchMode}
          />
        </View>
        {!registering && (
          <Text style={[screen.sub, {textAlign: 'center', marginTop: 18}]}>
            登录 GO ID 以继续使用你的账号。
          </Text>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
