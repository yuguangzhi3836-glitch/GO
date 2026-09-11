# GO Consumer Mobile — Sprint 2A

React Native / Expo native product surface for the complete hotel Golden Path.

Implemented screens: Login, Home, Search, Hotel Detail, Prebook/Booking Review, Booking Success, GO Trips, Order Detail, Change, Cancel/Refund, 365-day property-only Stay Credit, Wallet, Notifications, Profile, and GO Truth Quick Review.

Mobile event behavior:
- ORDER_CONFIRMED -> booking success push -> `go://trips/order/{order_id}`
- check-in reminder -> order deep link
- REFUND_COMPLETED -> refund push -> order deep link
- COMPENSATION_COMPLETED -> compensation push -> order deep link
- FULFILLMENT_COMPLETED -> first review invite scheduled four hours after checkout (inside locked 2–10 hour window) -> `go://reviews/{review_id}`
- if still NOT_REVIEWED, authenticated foreground app-open returns one Uber-style blocking Quick Review intent
- if review is COMPLETED, all later review jobs are cancelled / app-open returns NONE

Security: tokens live only in `expo-secure-store`; consumer-owned fare mutations use mobile wrappers that derive account ownership from JWT. Payment remains Authorization -> Supplier Book -> Capture.
