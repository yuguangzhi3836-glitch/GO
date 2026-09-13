from pathlib import Path
import importlib.util

ROOT=Path(__file__).resolve().parents[1]

def text(p): return (ROOT/p).read_text(encoding='utf-8')

def main():
    admin=text('frontend/admin/config.js')
    supplier=text('frontend/supplier/config.js')
    app=text('mobile/go-app/App.tsx')
    rooms=text('mobile/go-app/src/screens/RoomsScreen.tsx')
    ride=text('mobile/go-app/src/screens/RideReviewScreen.tsx')
    rental=text('mobile/go-app/src/screens/RentalReviewScreen.tsx')
    for token in ['酒店运营','机票运营','铁路运营','用车运营','租车运营','景点门票 / 体验','供应商管理','GO 推荐','GO 点评','GO Truth','GO 星级','GO Trips']:
        assert token in admin, token
    for token in ['supplierCommandCenter','supplierProductGraph','supplierOperatingSnapshot','supplierReviews','supplierRating','supplierPaymentFinance']:
        assert token in supplier, token
    assert 'HotelCompare' in app and "navigation.navigate('HotelCompare'" in rooms
    assert 'RidePayment' in app and "navigation.navigate('RidePayment'" in ride
    assert 'RentalPayment' in app and "navigation.navigate('RentalPayment'" in rental
    assert "navigate('RideSuccess')" not in ride
    assert "navigate('RentalSuccess')" not in rental
    main_py=text('src/go_hotel/main.py')
    assert 'operations_console_router' in main_py
    assert 'supplier_operations_router' in main_py
    print('OPERATIONS_CONSOLE_COMPLETION_GATE_V6.1: PASS')

if __name__=='__main__': main()
