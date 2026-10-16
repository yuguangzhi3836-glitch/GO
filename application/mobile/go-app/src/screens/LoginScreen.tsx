import React, {useEffect, useState} from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
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
import {
  API,
  ConsumerRegistrationPolicy,
  getConsumerRegistrationPolicy,
  getRegistrationTermDocument,
  register as apiRegister,
  requestRegistrationCode,
} from '../api/client';

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
  maxLength,
  textContentType,
  autoComplete,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  secureTextEntry?: boolean;
  keyboardType?: 'default' | 'email-address' | 'number-pad';
  autoCapitalize?: 'none' | 'sentences';
  maxLength?: number;
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
        maxLength={maxLength}
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
  const [verificationCode, setVerificationCode] = useState('');
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [policy, setPolicy] = useState<ConsumerRegistrationPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [challengeId, setChallengeId] = useState('');
  const [challengeEmail, setChallengeEmail] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [document, setDocument] = useState<{title:string;content:string} | null>(null);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const registering = mode === 'register';

  useEffect(() => {
    let mounted = true;
    if (mode !== 'register') return () => { mounted = false; };
    setPolicyLoading(true);
    getConsumerRegistrationPolicy().then(value => {
      if (mounted) setPolicy(value);
    }).catch(error => {
      if (mounted) {
        setPolicy(null);
        Alert.alert('无法读取注册条款', errorMessage(error));
      }
    }).finally(() => { if (mounted) setPolicyLoading(false); });
    return () => { mounted = false; };
  }, [mode]);

  const registrationDecisions = (current: ConsumerRegistrationPolicy) => {
    const decisions: Record<string, string> = {};
    for (const termId of Object.keys(current.versions)) {
      if (termId === 'consumer_service_terms') decisions[termId] = 'CONTRACT_ACCEPTED';
      else if (termId === 'privacy_policy') decisions[termId] = 'NOTICE_ACKNOWLEDGED';
      else throw new Error(`UNSUPPORTED_REGISTRATION_TERM:${termId}`);
    }
    for (const termId of current.deferred || []) decisions[termId] = 'DEFERRED';
    return decisions;
  };

  const openTerm = async (path: string) => {
    setDocumentLoading(true);
    try {
      const result = await getRegistrationTermDocument(path);
      setDocument({title: `${result.title}（${result.version} · ${result.status}）`, content: result.content});
    } catch (error) {
      Alert.alert('无法打开条款', errorMessage(error));
    } finally { setDocumentLoading(false); }
  };

  const sendVerificationCode = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      Alert.alert('邮箱格式不正确', '请先输入有效的邮箱地址。');
      return;
    }
    if (!acceptedTerms || !policy || !policy.acceptance_enabled || !policy.enabled) {
      Alert.alert('暂时无法注册', '请先加载并确认当前注册条款。');
      return;
    }
    setSendingCode(true);
    try {
      const result:any = await requestRegistrationCode({
        email: normalizedEmail,
        accepted_terms: true,
        term_versions: policy.versions,
        term_hashes: policy.term_hashes,
        registration_decisions: registrationDecisions(policy),
      });
      const nextChallengeId = result?.data?.challenge_id;
      if (typeof nextChallengeId !== 'string' || !nextChallengeId) throw new Error('INVALID_CHALLENGE_RESPONSE');
      setChallengeId(nextChallengeId);
      setChallengeEmail(normalizedEmail);
      setVerificationCode('');
      Alert.alert('验证码已发送', '请查看邮箱并输入收到的 6 位验证码。');
    } catch (error) {
      Alert.alert('发送验证码失败', errorMessage(error));
    } finally { setSendingCode(false); }
  };

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
    if (!policy || !policy.acceptance_enabled || !policy.enabled) {
      Alert.alert('暂时无法注册', '当前注册条款不可用，请稍后重试。');
      return;
    }
    if (challengeEmail !== normalizedEmail || !challengeId) {
      Alert.alert('需要邮箱验证', '请先为当前邮箱发送验证码。');
      return;
    }
    if (!/^\d{6}$/.test(verificationCode.trim())) {
      Alert.alert('验证码格式不正确', '请输入邮箱收到的 6 位验证码。');
      return;
    }

    setBusy(true);
    try {
      await apiRegister({
        email: normalizedEmail,
        password,
        display_name: displayName.trim() || undefined,
        accepted_terms: true,
        term_versions: policy.versions,
        term_hashes: policy.term_hashes,
        registration_decisions: registrationDecisions(policy),
        challenge_id: challengeId,
        verification_code: verificationCode.trim(),
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      const status = typeof error === 'object' && error !== null && 'status' in error
        ? String((error as {status?: unknown}).status ?? 'unknown')
        : 'unavailable';
      const termsDebug = Object.entries(policy.versions).map(([key, value]) => `${key}=${value}`).join('\n');
      Alert.alert(
        'Registration failed',
        `${errorMessage(error)}\n\nHTTP: ${status}\nAPI: ${API}\nError code: ${detail}\nSubmitted terms:\n${termsDebug}`,
      );
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
    setChallengeId('');
    setChallengeEmail('');
    setVerificationCode('');
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
            onChangeText={value => {
              setEmail(value);
              if (value.trim().toLowerCase() !== challengeEmail) {
                setChallengeId('');
                setChallengeEmail('');
                setVerificationCode('');
              }
            }}
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

          {registering && policyLoading && (
            <View style={{flexDirection:'row',alignItems:'center',marginTop:16}}>
              <ActivityIndicator color={GO.blue} />
              <Text style={[screen.sub,{marginLeft:8}]}>正在读取当前注册条款…</Text>
            </View>
          )}

          {registering && policy && (
            <View style={{marginTop:16,padding:12,borderRadius:12,backgroundColor:'rgba(7,27,85,0.05)'}}>
              <Text style={{fontSize:13,fontWeight:'700',color:GO.slate}}>
                当前注册条款 · {policy.status}{policy.formal_approval_pending ? '（待正式审批）' : ''}
              </Text>
              {policy.documents.map(item => (
                <Pressable key={item.id} onPress={() => openTerm(item.content_url)} style={{paddingTop:10}}>
                  <Text style={{fontSize:13,color:GO.blue,textDecorationLine:'underline'}}>
                    {item.title} · {item.version} · 查看内容
                  </Text>
                </Pressable>
              ))}
              {policy.deferred?.includes('personal_vault_terms') && (
                <Text style={[screen.sub,{marginTop:8,fontSize:12}]}>
                  个人信息库条款本次延期确认，不会因注册而启用个人信息库。
                </Text>
              )}
            </View>
          )}

          {registering && !policyLoading && !policy && (
            <Text style={[screen.sub,{marginTop:12,color:'#9B2C2C'}]}>
              无法读取服务端注册策略，请检查网络后切换登录/注册页面重试。
            </Text>
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
                我已阅读并同意当前显示的 GO 服务条款与隐私政策。个人信息库条款如标记为延期，本次不会启用个人信息库。
              </Text>
            </Pressable>
          )}

          {registering && (
            <View style={{marginTop:8}}>
              <Btn
                title={sendingCode ? '正在发送验证码…' : challengeId && challengeEmail === email.trim().toLowerCase() ? '重新发送邮箱验证码' : '发送邮箱验证码'}
                secondary
                disabled={busy || sendingCode || policyLoading || !policy?.enabled || !acceptedTerms}
                onPress={sendVerificationCode}
              />
              <Input
                label="邮箱验证码"
                placeholder="输入邮箱收到的 6 位验证码"
                value={verificationCode}
                onChangeText={setVerificationCode}
                keyboardType="number-pad"
                autoCapitalize="none"
                maxLength={6}
              />
            </View>
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
      <Modal visible={!!document || documentLoading} animationType="slide" onRequestClose={() => setDocument(null)}>
        <View style={{flex:1,backgroundColor:GO.ivory,paddingTop:Platform.OS==='ios'?56:24}}>
          <View style={{paddingHorizontal:20,paddingBottom:12,flexDirection:'row',justifyContent:'space-between',alignItems:'center'}}>
            <Text style={{flex:1,fontSize:16,fontWeight:'700',color:GO.slate}} numberOfLines={2}>
              {document?.title || '正在加载条款…'}
            </Text>
            <Pressable onPress={() => setDocument(null)} style={{padding:10}}>
              <Text style={{color:GO.blue,fontWeight:'600'}}>关闭</Text>
            </Pressable>
          </View>
          {documentLoading
            ? <ActivityIndicator style={{marginTop:32}} color={GO.blue} />
            : <ScrollView contentContainerStyle={{padding:20,paddingTop:8}}>
                <Text selectable style={{fontSize:14,lineHeight:22,color:GO.slate}}>{document?.content}</Text>
              </ScrollView>}
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}
