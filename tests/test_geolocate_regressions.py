import math
import subprocess
import sys
from xml.etree import ElementTree as ET
import pytest
from rescueswarm.geolocate import geolocate_person, COT_UNKNOWN, EARTH_RADIUS_M


def message(box=(300, 200, 340, 240)):
    return {'status':'success','image_size':{'width':640,'height':480},
            'detections':[{'label':'person','confidence':.9,'box_xyxy':list(box)}]}


def run(msg=None, **kwargs):
    args=dict(camera_latitude=0,camera_longitude=0,altitude_m=100,
              horizontal_fov_deg=90,vertical_fov_deg=60)
    args.update(kwargs)
    return ET.fromstring(geolocate_person(msg or message(),**args))


def test_import_and_flat_mode_need_no_terrain_dependency():
    code='import sys; sys.modules["srtm"]=None; from rescueswarm.geolocate import geolocate_person'
    subprocess.run([sys.executable,'-c',code],check=True)
    assert float(run().find('point').get('hae')) == COT_UNKNOWN


def test_new_sightings_have_unique_ids_and_explicit_updates_are_stable():
    assert run().get('uid') != run(message((400,200,430,240))).get('uid')
    assert run(uid='run/image/person-0').get('uid') == run(uid='run/image/person-0').get('uid')
    assert run(uid='person<&"').get('uid') == 'person<&"'


def test_prior_high_fov_no_hit_bug_now_reaches_ground():
    p=run(message((620,200,640,240)),horizontal_fov_deg=170,
          elevation_fn=lambda lat,lon:0,terrain_datum='hae').find('point')
    expected_east=100*((630/640-.5)*2*math.tan(math.radians(85)))
    assert float(p.get('lon')) == pytest.approx(math.degrees(expected_east/EARTH_RADIUS_M),abs=1e-6)
    assert float(p.get('hae')) == pytest.approx(0,abs=.1)


def test_unreachable_terrain_raises_instead_of_publishing_air_point():
    with pytest.raises(ValueError,match='no terrain intersection'):
        run(message((620,200,640,240)),horizontal_fov_deg=179.9,elevation_fn=lambda lat,lon:0)


def test_refined_sloping_intersection_matches_analytic_geometry():
    # At image x=480, east=.5*down; terrain height=.2*east.
    def terrain(lat,lon):return .2*math.radians(lon)*EARTH_RADIUS_M
    p=run(message((460,200,500,240)),elevation_fn=terrain,terrain_datum='hae').find('point')
    assert float(p.get('lon')) == pytest.approx(math.degrees((50/1.1)/EARTH_RADIUS_M),abs=1e-6)
    assert float(p.get('hae')) == pytest.approx(100-100/1.1,abs=.1)


@pytest.mark.parametrize('datum,offset,expected',[('msl',None,COT_UNKNOWN),('msl',30,230),('msl',-30,170),('hae',None,200)])
def test_height_datum_conversion(datum,offset,expected):
    p=run(elevation_fn=lambda lat,lon:200,terrain_datum=datum,geoid_offset_m=offset).find('point')
    assert float(p.get('hae'))==pytest.approx(expected,abs=.1)


def test_flat_ground_explicit_hae_and_unknown_accuracy():
    p=run(flat_ground_hae_m=215).find('point')
    assert float(p.get('hae'))==215
    assert float(p.get('ce'))==float(p.get('le'))==COT_UNKNOWN


@pytest.mark.parametrize('missing',[None,float('nan'),float('inf')])
def test_no_silent_flat_baseline_when_terrain_disappears_mid_ray(missing):
    def terrain(lat,lon): return 0 if lon==0 else missing
    with pytest.raises(ValueError,match='terrain unavailable or invalid'):
        run(message((460,200,500,240)),elevation_fn=terrain)


def test_mid_ray_provider_error_propagates():
    def terrain(lat,lon):
        if lon!=0: raise OSError('lost tile')
        return 0
    with pytest.raises(OSError,match='lost tile'):
        run(message((460,200,500,240)),elevation_fn=terrain)


@pytest.mark.parametrize('kwargs',[{'camera_pitch_deg':-45},{'camera_roll_deg':1},{'terrain_datum':'unknown'},
    {'geoid_offset_m':float('nan')},{'flat_ground_hae_m':float('inf')},{'stale_duration_sec':0},{'uid':''}])
def test_rejects_invalid_contract(kwargs):
    with pytest.raises(ValueError):run(**kwargs)


@pytest.mark.parametrize('field,value',[('label','car'),('confidence',float('nan')),('box_xyxy',[0,0,700,40]),('box_xyxy',[0,0,float('nan'),40])])
def test_wire_detection_validation(field,value):
    m=message();m['detections'][0][field]=value
    with pytest.raises(ValueError):run(m)
