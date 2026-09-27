"""Build a reviewable legal draft from an existing NON-SECRET operator record.

Never reads mail credentials; never approves terms or enables a live environment.
The source is operator-supplied, not inferred from blank fields or web search.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

COMPANY = '构行人工智能（黑龙江）有限公司'
EMAIL = 'postmaster@goaidirect.com'
ALPHABET = '0123456789ABCDEFGHJKLMNPQRTUWXY'
WEIGHTS = [1,3,9,27,19,26,16,17,20,29,25,13,8,24,10,30,28]


def validate_profile(profile):
    allowed = {'legal_name','registration_address','unified_social_credit_code','privacy_email','source_reference','delivery_evidence_ref','handling_evidence_ref'}
    if not isinstance(profile,dict) or set(profile)-allowed:
        raise ValueError('NON_SECRET_OPERATOR_PROFILE_REQUIRED')
    if profile.get('legal_name') != COMPANY or profile.get('privacy_email') != EMAIL:
        raise ValueError('OPERATOR_IDENTITY_CONFLICT')
    for key in ('registration_address','source_reference'):
        if not isinstance(profile.get(key),str) or not profile[key].strip():
            raise ValueError('EXISTING_OPERATOR_RECORD_INCOMPLETE')
    code = profile.get('unified_social_credit_code','')
    if not isinstance(code,str) or len(code)!=18 or any(x not in ALPHABET for x in code):
        raise ValueError('INVALID_SOCIAL_CREDIT_CODE')
    if ALPHABET[(31-sum(ALPHABET.index(c)*w for c,w in zip(code[:17],WEIGHTS))%31)%31] != code[-1]:
        raise ValueError('INVALID_SOCIAL_CREDIT_CODE')
    return profile


def synchronize(source, registry_path, destination, version):
    profile = validate_profile(json.loads(Path(source).read_text(encoding='utf-8')))
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',version) or 'draft' not in version.lower():
        raise ValueError('NEW_DRAFT_VERSION_REQUIRED')
    registry_path,destination=Path(registry_path),Path(destination)
    registry=json.loads(registry_path.read_text(encoding='utf-8'))
    # Refuse accidental rewriting of a reviewed/canonical package.
    if destination.exists():
        raise ValueError('DESTINATION_ALREADY_EXISTS')
    if version in {d['version'] for d in registry['documents']}:
        raise ValueError('NEW_DRAFT_VERSION_REQUIRED')
    registry['release_status']='DRAFT'
    registry['operator']={k:profile[k] for k in ('legal_name','registration_address','unified_social_credit_code')}
    registry['operator']['confirmation_source']=profile['source_reference']
    registry['contact_channels']={'privacy_email':EMAIL,'confirmation_source':profile['source_reference'],
        'delivery_verified':bool(profile.get('delivery_evidence_ref')),
        'delivery_evidence_ref':profile.get('delivery_evidence_ref'),
        'handling_evidence_ref':profile.get('handling_evidence_ref')}
    unresolved=set(registry.get('unresolved') or [])
    unresolved.discard('OPERATOR_REGISTRATION_DETAILS_MISSING')
    if profile.get('delivery_evidence_ref') and profile.get('handling_evidence_ref'):
        unresolved.discard('CONTACT_DELIVERY_AND_HANDLING_UNVERIFIED')
    unresolved.add('FORMAL_LEGAL_APPROVAL_MISSING')
    registry['unresolved']=sorted(unresolved)
    outputs={}
    for doc in registry['documents']:
        file=doc['file']
        if Path(file).name!=file or not file.endswith('.md'):
            raise ValueError('INVALID_DOCUMENT_PATH')
        raw=(registry_path.parent/file).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=doc['sha256']:
            raise ValueError('SOURCE_DOCUMENT_INTEGRITY_ERROR')
        text=raw.decode().replace(doc['version'],version)
        # Preserve the old wording for audit; make the synchronized facts explicit
        # as the controlling operator-information appendix in the NEW draft.
        text+='\n\n## 本版运营主体资料同步\n\n'
        text+='本节替换正文中关于注册地址、统一社会信用代码待补充的说明；其余业务与数据处理条款仍待审核。\n\n'
        text+=f"- 主体：{COMPANY}\n- 注册地址：{profile['registration_address']}\n- 统一社会信用代码：{profile['unified_social_credit_code']}\n- 联系邮箱：{EMAIL}\n"
        outputs[file]=text.encode()
        doc.update(version=version,status='DRAFT',approval=None,effective_at=None,sha256=hashlib.sha256(outputs[file]).hexdigest())
    destination.mkdir(parents=True)
    for name,raw in outputs.items():
        (destination/name).write_bytes(raw)
    registry['profile_source_sha256']=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    (destination/'registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
    return {'status':'DRAFT_SYNCHRONIZED','version':version,'documents':len(outputs),'registration_enabled':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--registry',required=True)
    parser.add_argument('--destination',required=True)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    print(json.dumps(synchronize(args.profile,args.registry,args.destination,args.version)))
