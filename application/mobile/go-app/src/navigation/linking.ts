import * as Linking from 'expo-linking';
export const linking={
  prefixes:[Linking.createURL('/'),'go://','https://go.travel/app'],
  config:{screens:{
    Main:{screens:{Home:'home',Search:'search',Trips:'trips',Wallet:'wallet',Profile:'profile'}},
    HotelDetail:'hotels/:hotelId',DirectValue:'hotels/:hotelId/direct-value',OrderDetail:'trips/order/:orderId',QuickReview:'reviews/:reviewId',Notifications:'notifications',TravelProfileVault:'profile/vault',TravelProfileImport:'profile/import'
  }}
};
