"""Staging operator helper: enqueue Harbin first-city hotel discovery/build.
Does not modify migration lineage and does not publish media or upgrade GO Direct.
"""
from go_hotel.services.regional_hotel_build import regional_hotel_build_service

if __name__ == '__main__':
    result=regional_hotel_build_service.start(
        mode='REGION', country='CN', province='黑龙江省', city='哈尔滨市', actor='RC17.9.1_STAGING_OPERATOR'
    )
    print(result)
