import * as Linking from 'expo-linking';
import type {LinkingOptions, NavigatorScreenParams} from '@react-navigation/native';

type MainTabParams = {Home: undefined; Search: undefined; Trips: undefined; Wallet: undefined; Profile: undefined};
type LinkedRootParams = {
  Main: NavigatorScreenParams<MainTabParams>;
  HotelDetail: {hotelId: string};
  DirectValue: {hotelId: string};
  OrderDetail: {orderId: string};
  QuickReview: {reviewId: string};
  Notifications: undefined;
  TravelProfileVault: undefined;
  TravelProfileImport: undefined;
};
export const linking: LinkingOptions<LinkedRootParams> = {
  prefixes:[Linking.createURL('/'),'go://','https://go.travel/app'],
  config:{screens:{
    Main:{screens:{Home:'home',Search:'search',Trips:'trips',Wallet:'wallet',Profile:'profile'}},
    HotelDetail:'hotels/:hotelId',DirectValue:'hotels/:hotelId/direct-value',OrderDetail:'trips/order/:orderId',QuickReview:'reviews/:reviewId',Notifications:'notifications',TravelProfileVault:'profile/vault',TravelProfileImport:'profile/import'
  }}
};
