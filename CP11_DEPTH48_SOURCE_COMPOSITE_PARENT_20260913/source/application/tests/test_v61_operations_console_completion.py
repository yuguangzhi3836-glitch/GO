from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def text(path): return (ROOT/path).read_text(encoding='utf-8')

def test_go_admin_has_all_vertical_and_go_core_modules():
    cfg=text('frontend/admin/config.js')
    for token in [
        '酒店运营','机票运营','铁路运营','用车运营','租车运营','景点门票 / 体验',
        '供应商管理','GO 推荐','GO 点评','GO Truth','GO 星级','GO Trips'
    ]:
        assert token in cfg

def test_supplier_console_uses_operational_workbenches():
    cfg=text('frontend/supplier/config.js')
    for custom in ['supplierCommandCenter','supplierProductGraph','supplierOperatingSnapshot','supplierJudgments','supplierPaymentFinance','supplierReviews','supplierRating']:
        assert custom in cfg

def test_consumer_hotel_has_compare_before_booking_review():
    app=text('mobile/go-app/App.tsx')
    rooms=text('mobile/go-app/src/screens/RoomsScreen.tsx')
    assert 'HotelCompare' in app
    assert "navigation.navigate('HotelCompare'" in rooms
    assert "navigation.navigate('BookingReview'" not in rooms

def test_mobility_has_explicit_payment_before_success():
    app=text('mobile/go-app/App.tsx')
    ride=text('mobile/go-app/src/screens/RideReviewScreen.tsx')
    rental=text('mobile/go-app/src/screens/RentalReviewScreen.tsx')
    assert 'RidePayment' in app and 'RentalPayment' in app
    assert "navigation.navigate('RidePayment'" in ride
    assert "navigation.navigate('RentalPayment'" in rental
    assert "navigate('RideSuccess')" not in ride
    assert "navigate('RentalSuccess')" not in rental

def test_admin_operations_api_is_registered():
    main=text('src/go_hotel/main.py')
    route=text('src/go_hotel/api/routes/operations_console.py')
    assert 'operations_console_router' in main
    assert 'supplier_operations_router' in main
    for v in ['HOTEL','FLIGHT','RAIL','RIDE','RENTAL','ATTRACTION']:
        assert v in route
    for path in ['/suppliers','/reviews','/recommendations','/stars','/truth','/trips']:
        assert path in route
