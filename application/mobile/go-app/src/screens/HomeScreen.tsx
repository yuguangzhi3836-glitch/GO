import React,{useEffect,useState}from'react';
import{ScrollView,Text,View,Pressable,StyleSheet,Image}from'react-native';
import{GO,screen,type}from'../design';
import{Brand,SubBrand}from'../components/GO';
import{api}from'../api/client';
import{registerPush}from'../notifications/registerPush';

const category=[['▦','酒店','Search'],['✈','机票','FlightSearch'],['▣','火车票','RailSearch'],['▰','租车','RentalSearch'],['⌁','景点玩乐','AttractionSearch']];
const values=[['直连','直连官方','交易更直接'],['推荐','独立判断','只推荐值得的'],['礼遇','官方专享','尊享更多礼遇']];

export default function Home({navigation}:any){
  const[data,setData]=useState<any>(null),[profileReady,setProfileReady]=useState<boolean|null>(null),[error,setError]=useState('');
  useEffect(()=>{api('/v1/consumer/home').then(r=>setData(r.data)).catch(e=>setError(e.message));api('/v1/consumer/profile/completeness').then(r=>setProfileReady(Boolean(r.data?.profile_ready))).catch(()=>setProfileReady(null));registerPush().catch(()=>{})},[]);
  const recs=data?.recommendations||[];
  return <ScrollView style={screen.root} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
    <View style={s.masterHeader}><Image source={require('../../assets/brand/go-si-direct.png')} accessibilityLabel="GO SI DIRECT+ 发现全世界 直接向官方预订" resizeMode="contain" style={s.masterLockup}/></View>

    <View style={s.categories}>{category.map(([icon,label,to],i)=><Pressable key={label} style={s.cat} onPress={()=>navigation.navigate(to)}><View style={s.catIcon}><Text style={s.catGlyph}>{icon}</Text></View><Text style={s.catText}>{label}</Text></Pressable>)}</View>

    {profileReady===false?<Pressable style={s.profileBuild} onPress={()=>navigation.navigate('TravelProfileImport')}><View style={{flex:1}}><Text style={s.profileBuildEyebrow}>BRING YOUR TRAVEL PROFILE TO GO</Text><Text style={s.profileBuildTitle}>一键建立我的旅行资料</Text><Text style={s.profileBuildCopy}>把已有旅客、证件、会员和偏好带到 GO，以后预订不用重复填写。</Text></View><Text style={s.profileBuildArrow}>›</Text></Pressable>:null}

    <View style={s.heroRow}>
      <Pressable style={[s.hero,s.ai]} onPress={()=>navigation.navigate('Search')}><View style={s.heroBrand}><SubBrand name="AI"/><Text style={s.chev}>›</Text></View><Text style={s.heroTitle}>你想去哪儿，{`\n`}想怎么旅行？</Text><Text style={s.heroCopy}>说出完整需求，让 GO 帮你想、帮你找、帮你规划。</Text><View style={s.voiceWrap}><View style={[s.glow,s.glow3]}/><View style={[s.glow,s.glow2]}/><View style={[s.glow,s.glow1]}/><View style={[s.voice,{backgroundColor:GO.blue}]}><Text style={s.voiceGo}>GO</Text><Text style={s.voiceMic}>●</Text></View></View><Text style={s.voiceLabel}>按住说话</Text></Pressable>

      <Pressable style={[s.hero,s.offer]} onPress={()=>navigation.navigate('Offer')}><View style={s.heroBrand}><SubBrand name="Offer"/><Text style={s.chev}>›</Text></View><Text style={s.heroTitle}>告诉我的需求</Text><Text style={s.heroCopy}>把目的地、日期、房型或会议需求交给 GO，让官方直接报价。</Text><View style={s.voiceWrap}><View style={[s.glow,s.glow3,{borderColor:'rgba(255,75,22,.08)'}]}/><View style={[s.glow,s.glow2,{borderColor:'rgba(255,75,22,.12)'}]}/><View style={[s.glow,s.glow1,{borderColor:'rgba(255,75,22,.18)'}]}/><View style={[s.voice,{backgroundColor:GO.orange}]}><Text style={s.voiceGo}>GO</Text><Text style={s.voiceMic}>●</Text></View></View><Text style={[s.voiceLabel,{color:GO.orange}]}>按住说话</Text></Pressable>
    </View>

    <View style={s.valueBand}>{values.map(([name,l1,l2],i)=><React.Fragment key={name}><View style={s.valueItem}><View style={s.valueHead}><Brand compact/><Text style={s.valueName}>{name}</Text></View><Text style={s.valueCopy}>{l1}{`\n`}{l2}</Text></View>{i<values.length-1?<View style={s.valueDivider}/>:null}</React.Fragment>)}</View>

    <View style={s.sectionHead}><View style={s.recommendBrand}><Brand compact/><Text style={s.recTitle}>推荐</Text></View><Text style={s.why}>查看全部 ›</Text></View>
    {error?<View style={s.truthCard}><Text style={screen.sub}>推荐加载失败：{error}</Text></View>:recs.length===0?<View style={s.truthCard}><Text style={screen.h2}>暂无个性化推荐</Text><Text style={[screen.sub,{marginTop:6}]}>完成偏好或搜索后生成个性化推荐。</Text></View>:<ScrollView horizontal showsHorizontalScrollIndicator={false}>{recs.map((x:any)=><Pressable key={x.hotel_id} style={s.recCard} onPress={()=>navigation.navigate('HotelDetail',{hotelId:x.hotel_id})}>{x.image_url?<Image source={{uri:x.image_url}} style={s.recImage}/>:<View style={s.recFallback}/>}<View style={s.overlay}/><View style={s.recBadge}><Text style={s.recBadgeText}>GO 推荐</Text></View><View style={s.recText}><Text style={s.recName}>{x.name}</Text><Text style={s.recReason} numberOfLines={2}>{x.reason_summary}</Text><Text style={s.rating}>{x.go_star_level?`GO ${x.go_star_level}`:'GO 推荐'}{x.go_score!=null?` · ${x.go_score}`:''}</Text></View></Pressable>)}</ScrollView>}
  </ScrollView>
}

const s=StyleSheet.create({
  content:{paddingHorizontal:12,paddingTop:18,paddingBottom:120,backgroundColor:GO.white},
  masterHeader:{minHeight:84,justifyContent:'center'},masterLockup:{width:'100%',aspectRatio:6796/1080},
  categories:{flexDirection:'row',justifyContent:'space-between',marginTop:14,marginBottom:20,paddingHorizontal:4},cat:{alignItems:'center',width:'19%'},catIcon:{width:44,height:44,borderRadius:22,borderWidth:1,borderColor:GO.line,backgroundColor:GO.white,alignItems:'center',justifyContent:'center'},catGlyph:{fontSize:20,fontWeight:'600',color:GO.navy},catText:{fontSize:12,fontWeight:'500',color:GO.navy,marginTop:7,textAlign:'center'},
  profileBuild:{flexDirection:'row',alignItems:'center',backgroundColor:GO.white,borderWidth:1,borderColor:'rgba(8,120,249,.12)',borderRadius:GO.radius.l,padding:16,marginBottom:12},profileBuildEyebrow:{fontSize:10,fontWeight:'600',letterSpacing:1,color:GO.blue},profileBuildTitle:{...type.titleS,color:GO.navy,marginTop:4},profileBuildCopy:{...type.captionS,color:GO.slate,marginTop:4},profileBuildArrow:{fontSize:28,color:GO.blue,marginLeft:10},
  heroRow:{flexDirection:'row',gap:8},hero:{flex:1,minHeight:296,borderRadius:GO.radius.l,padding:16,borderWidth:1,overflow:'hidden'},ai:{backgroundColor:'#F6F9FF',borderColor:'rgba(8,120,249,.10)'},offer:{backgroundColor:'#FFF8F5',borderColor:'rgba(255,75,22,.10)'},heroBrand:{flexDirection:'row',alignItems:'center',justifyContent:'space-between'},chev:{fontSize:24,color:GO.navy,fontWeight:'300'},heroTitle:{...type.titleM,color:GO.navy,marginTop:16},heroCopy:{...type.captionS,color:GO.slate,marginTop:7},
  voiceWrap:{height:112,alignItems:'center',justifyContent:'center',marginTop:14},glow:{position:'absolute',borderWidth:1,borderColor:'rgba(8,120,249,.10)',borderRadius:999},glow3:{width:108,height:108},glow2:{width:92,height:92,borderColor:'rgba(8,120,249,.14)'},glow1:{width:82,height:82,borderColor:'rgba(8,120,249,.18)'},voice:{width:78,height:78,borderRadius:39,alignItems:'center',justifyContent:'center'},voiceGo:{color:'white',fontSize:20,fontWeight:'600',letterSpacing:-1},voiceMic:{position:'absolute',bottom:12,color:'white',fontSize:8},voiceLabel:{...type.captionL,color:GO.blue,textAlign:'center',marginTop:2},
  valueBand:{flexDirection:'row',alignItems:'stretch',marginTop:12,borderTopWidth:1,borderBottomWidth:1,borderColor:GO.line,paddingVertical:12},valueItem:{flex:1,paddingHorizontal:8},valueDivider:{width:1,backgroundColor:GO.line},valueHead:{flexDirection:'row',alignItems:'center',justifyContent:'center'},valueName:{fontSize:14,fontWeight:'500',color:GO.navy,marginLeft:4},valueCopy:{fontSize:11,lineHeight:16,fontWeight:'400',color:'rgba(7,27,85,.50)',marginTop:5,textAlign:'center'},
  sectionHead:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',marginTop:20,marginBottom:10},recommendBrand:{flexDirection:'row',alignItems:'center'},recTitle:{...type.titleS,color:GO.navy,marginLeft:6},why:{...type.captionL,color:GO.blue},truthCard:{backgroundColor:GO.white,borderRadius:GO.radius.l,padding:16,borderWidth:1,borderColor:GO.line},
  recCard:{width:208,height:240,marginRight:8,borderRadius:GO.radius.m,overflow:'hidden',backgroundColor:'#EDEFF2'},recImage:{position:'absolute',width:'100%',height:'100%'},recFallback:{position:'absolute',width:'100%',height:'100%',backgroundColor:'#4A5565'},overlay:{position:'absolute',left:0,right:0,bottom:0,height:120,backgroundColor:'rgba(0,10,40,.38)'},recBadge:{position:'absolute',top:8,left:8,height:20,paddingHorizontal:8,borderRadius:999,backgroundColor:'rgba(7,27,85,.90)',justifyContent:'center'},recBadgeText:{fontSize:10,fontWeight:'500',color:'white'},recText:{position:'absolute',left:12,right:12,bottom:10},recName:{color:'white',fontSize:14,lineHeight:20,fontWeight:'600'},recReason:{color:'rgba(255,255,255,.90)',fontSize:11,lineHeight:16,marginTop:3},rating:{color:'rgba(255,255,255,.96)',fontSize:12,lineHeight:18,fontWeight:'500',marginTop:5}
});
