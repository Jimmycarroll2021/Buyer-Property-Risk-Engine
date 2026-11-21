"""Reproducibly compile supplied design registers into runtime configuration."""
from pathlib import Path
import json, shutil, urllib.parse, re

BASE=Path(__file__).resolve().parents[1]
WORK=BASE.parent
INPUT=BASE/'reference/ingestion_catalogue.json'

def run():
    data=json.loads(INPUT.read_text())
    cfg=BASE/'config';cfg.mkdir(exist_ok=True)
    groups={}
    for entry in data['source_entries']:
        groups.setdefault(entry['canonical_id'],[]).append(entry)
    sources=[]
    for sid,entries in sorted(groups.items()):
        preferred=next((x for x in entries if x['catalogue']=='propertypeek'),entries[0])
        r=preferred['record']; pp=preferred['catalogue']=='propertypeek'
        endpoint=r.get('Endpoint / Portal URL') if pp else r.get('Request or download URL')
        mode=str(r.get('Access Protocol') if pp else r.get('Access mode')).lower()
        title=r.get('Title') if pp else r.get('Dataset')
        url=urllib.parse.urlsplit(endpoint or '')
        parameters={}
        if 'arcgis' in mode and re.search(r'/(?:FeatureServer|MapServer)/\d+(?:/query)?$',url.path,re.I):
            adapter='arcgis'
            endpoint=urllib.parse.urlunsplit((url.scheme,url.netloc,re.sub('/query$','',url.path), '', ''))
        elif 'socrata_soda' in mode or '/resource/' in (endpoint or ''):
            adapter='socrata'
        elif 'rba.gov.au' in (endpoint or '') and '.csv' in (endpoint or ''):
            adapter='rba_csv'
        elif '2egm-dieb' in (endpoint or ''):
            adapter='crime_xlsx'
            parameters={'catalogue_id':'2egm-dieb','file_url':'https://www.data.act.gov.au/api/views/2egm-dieb/files/13e57c74-edc3-44e9-8c88-93938ea4cc4d?download=true&filename=Website_Qtrly_Jun25.xlsx','expected_vintage':'2025 Q2','discover_latest':True}
        elif 'sdmx' in mode:
            adapter='sdmx_csv'
        elif 'gtfs' in mode or 'google_transit.zip' in (endpoint or ''):
            adapter='gtfs_zip'
            parameters={'username_env':'TRANSPORT_ACT_USERNAME','password_env':'TRANSPORT_ACT_PASSWORD','api_key_env':'TRANSPORT_ACT_API_KEY'}
        elif 'api_key_required' in mode or 'manual' in mode or 'restricted' in mode:
            adapter='manual'
        elif any(s in mode for s in ('catalog','catalogue','portal','stac','hub','web','wfs','csw','overpass','location_lookup')):
            adapter='discovery'
        elif 'json' in mode:
            adapter='generic_json'
        elif any(s in mode for s in ('download','csv','xlsx','cog','geotiff','bulk')):
            adapter='file_download'
        else:adapter='manual'
        sources.append({
          'source_id':sid,'title':title,'adapter':adapter,'endpoint':endpoint,
          'jurisdiction':r.get('Jurisdiction','ACT/National'),'category':r.get('Category',r.get('Theme')),
          'access_status':r.get('Operational Status',r.get('Verification status','UNVERIFIED')),
          'licence_status':'REVIEW_REQUIRED','enabled':False,
          'rights':{'process':False,'retain_raw':False,'display_raw':False,'display_derived':False},
          'refresh_policy':r.get('Refresh / vintage','Check source release metadata; not a promise of source updates'),
          'source_aliases':[x['catalogue']+':'+str(x['source_record_id']) for x in entries],
          'source_claims':entries,'parameters':parameters,
          'readiness_note':'Recorded catalogue claims are not current completeness, licence or assessment evidence.',
          'limits':{'max_records':1000,'max_bytes':20000000,'timeout_seconds':30}
        })
    # Retain explicit, reviewed source activation independently of uploaded claims.
    override_path=cfg/'source_overrides.json'
    overrides=json.loads(override_path.read_text()) if override_path.exists() else {}
    for source in sources:
        source.update(overrides.get('sources',{}).get(source['source_id'],{}))
    # Logical source families remain separate from physical endpoint aliases.
    (cfg/'sources.json').write_text(json.dumps({'version':'0.1.0','sources':sources,'baseline_source_families':data['baseline_source_register'],'unresolved_overlap_note':overrides.get('unresolved_overlap_note','Exact layer aliases reconciled. Portal interfaces and semantic source families can still overlap.'),'resolved_alias_relations':overrides.get('resolved_alias_relations',[])},indent=2))
    private_domains={'Building condition','Insurance','Buyer finance','Financial resilience','Legal and title','Strata and shared property'}
    checks=[]
    for s in data['baseline_signal_register']['signals']:
        critical=any(k in s['rule_ids'] for k in ('ID01','FL01','FL02','FI01','BD01','BD02','LG01','IN01','FN01','FN02','FN03','FN04'))
        checks.append({'check_id':s['signal_id'],'label':s['signal_name'],'domain':s['domain'],'critical':critical,'required':True,'public_check':s['domain'] not in private_domains and not any(k in s['rule_ids'] for k in ('BD01','BD02','LG01','IN01','FN01','FN02','FN03','FN04')),'rule_ids':s['rule_ids'],'phase':s['phase'],'raw_inputs':s['raw_inputs'],'source_ids':s['source_ids'],'processing_specification':s['processing'],'missing_evidence_handling':s['missing_evidence_handling']})
    (cfg/'checks.json').write_text(json.dumps({'version':'0.1.0','checks':checks},indent=2))
    for key,name in [('baseline_rule_register','rules.json'),('baseline_signal_register','signals.json'),('acceptance_specifications','acceptance_specifications.json')]:
        (cfg/name).write_text(json.dumps(data[key],indent=2))
    (cfg/'reference_risks.json').write_text(json.dumps({'source_vintage':'2021','purpose':'Reference questions only. Ratings are not property findings.','project_risks':data['reference_risks'],'sector_risks':data['reference_sector_risks'],'capacity_report':data['capacity_report_reference']},indent=2))
    (cfg/'input_schema_claims.json').write_text(json.dumps({'status':'UPLOADED_CATALOGUE_CLAIMS','rows':data['schema_observations_from_uploaded_workbook'],'licence_claims':data['licence_claims'],'access_gaps':data['access_gaps'],'quality_findings':data['quality_findings']},indent=2))
    print(json.dumps({'sources':len(sources),'checks':len(checks),'rule_families':len(data['baseline_rule_register'])}))

if __name__=='__main__':run()
