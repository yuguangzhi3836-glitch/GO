import {StyleSheet} from 'react-native';

// GO Consumer Design System 1.0 exact brand tokens.
// Candidate UI clarification: White/Neutral = Space; Navy = Structure;
// GO Blue = Interaction & Brand Signal; GO Orange = Offer & Value Signal.
export const GO = {
  navy:'#071B55', blue:'#0878F9', orange:'#FF4B16', coral:'#FF4B16',
  white:'#FFFFFF', neutral:'#FAFAF8', ivory:'#FAFAF8', black:'#000000', ink:'#071B55',
  slate:'rgba(7,27,85,0.68)', tertiary:'rgba(7,27,85,0.50)', disabled:'rgba(7,27,85,0.30)',
  line:'rgba(7,27,85,0.08)', mist:'#F7F8FA', pale:'#FFF8F5', bluePale:'#F6F9FF',
  green:'#15803D', greenPale:'#ECFDF3', amber:'#B45309', amberPale:'#FFF7E8',
  radius:{s:8,m:12,l:16,xl:20,pill:999},
  shadow:{shadowColor:'#071B55',shadowOpacity:.035,shadowRadius:12,shadowOffset:{width:0,height:2},elevation:1}
};

export const type = {
  display:{fontSize:22,lineHeight:30,fontWeight:'600' as const},
  titleL:{fontSize:20,lineHeight:28,fontWeight:'600' as const},
  titleM:{fontSize:18,lineHeight:26,fontWeight:'600' as const},
  titleS:{fontSize:16,lineHeight:24,fontWeight:'600' as const},
  bodyL:{fontSize:15,lineHeight:23,fontWeight:'400' as const},
  bodyM:{fontSize:14,lineHeight:22,fontWeight:'400' as const},
  bodyS:{fontSize:13,lineHeight:20,fontWeight:'400' as const},
  captionL:{fontSize:12,lineHeight:18,fontWeight:'500' as const},
  captionS:{fontSize:11,lineHeight:16,fontWeight:'400' as const},
};

export const screen = StyleSheet.create({
  root:{flex:1,backgroundColor:GO.white}, safe:{flex:1,backgroundColor:GO.white}, scroll:{flex:1},
  content:{paddingHorizontal:16,paddingTop:16,paddingBottom:120},
  title:{...type.display,color:GO.navy}, h1:{...type.titleL,color:GO.navy}, h2:{...type.titleM,color:GO.navy},
  body:{...type.bodyL,color:GO.navy}, sub:{...type.bodyS,color:GO.slate},
  card:{backgroundColor:GO.white,borderRadius:GO.radius.l,padding:16,marginTop:12,borderWidth:1,borderColor:GO.line,...GO.shadow},
  row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between'},
  divider:{height:1,backgroundColor:GO.line,marginVertical:16}, section:{marginTop:24},
  label:{...type.captionS,fontWeight:'500',color:GO.slate,textTransform:'uppercase',letterSpacing:.7},
});
