"""User-approved input mapping only. No imports or changes to optical code."""
import math

POLICY='user-approved-endpoint-midpoint-three-v1'

def finite(raw):
    if isinstance(raw,bool):raise ValueError('波长必须是有限数值，单位nm')
    value=float(raw)
    if not math.isfinite(value):raise ValueError('波长必须是有限数值')
    return value

def from_range_nm(low_nm,high_nm):
    low,high=finite(low_nm),finite(high_nm)
    if not 300<=low<=high<=1200:raise ValueError('波长范围要求300≤最小值≤最大值≤1200nm')
    values=[low,(low+high)/2,high]
    return dict(policy=POLICY,input_range_nm=[low,high],wavelengths_um=[w/1000 for w in values],
                primary_um=values[1]/1000,primary_index=1,weights=[1/3]*3,
                coincident_monochromatic_samples=low==high)

def from_file_wavelengths_um(wavelengths,original_primary_um=None,original_weights=None):
    if not isinstance(wavelengths,(list,tuple)) or not wavelengths:raise ValueError('文件中没有可验证的波长列表')
    waves=[finite(w) for w in wavelengths]
    result=from_range_nm(min(waves)*1000,max(waves)*1000)
    result['source_spectrum']=dict(wavelengths_um=list(waves),primary_um=original_primary_um,weights=original_weights)
    result['conversion_note']='按用户明确要求，新优化任务采用最小/中点/最大三点等权；原波长表仅保存作为来源记录'
    return result
