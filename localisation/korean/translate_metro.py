"""
Metro 2033 게임 한글화 자동 번역 스크립트
Ollama llama 3.1 8B 로컬 실행
"""

import os
import re
import time
from pathlib import Path
import requests
import json

# Ollama 설정
OLLAMA_API_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "mannix/llama3.1-8b-lexi:tools-q6_k"
LOG_FILE = "translation_errors.log"

SYSTEM_PROMPT = """You are a professional 'Metro 2033' game localization translator.

【 TOP PRIORITY RULES 】
1. Output ONLY translated data. No explanations or introductions.
2. Input line count MUST EXACTLY match output line count.
3. Preserve 100% of indentation and structure (Key: "Value").

【 ★ £ ICON CODE PROTECTION - VIOLATION FORBIDDEN ★ 】
1. **£ symbol followed by English text (e.g., £autonomy_icon, £trigger_text, £bullet_icon) are system icon codes.**
2. **NEVER translate to Korean.** Keep original English form exactly as-is.
   - WRONG: "자율성 아이콘" (X)
   - WRONG: "£Y교육" (X)
   - WRONG: "£가 필요합니다" (X)
   - CORRECT: "£autonomy_icon" (O)
   - CORRECT: "£trigger_yes" (O)
   - CORRECT: "£bullet_icon" (O)
3. Never insert Korean text immediately after £ symbol.
4. Examples: £command_power, £army_experience, £political_power_texticon, £pol_power, £autonomy_texticon, £D6_clue_texticon

【 TRANSLATION & OTHER RULES 】
1. Translate ONLY English text inside quotation marks (" ") to Korean.
2. Preserve special symbols: §Y, §G, §R, §!, \\n, [ ] - do NOT modify.
3. Atmosphere: Maintain dark, desperate post-apocalyptic tone.
   - Stalker -> 스토커, Hanza -> 한자, Artyom -> 아르티옴, Metro -> 메트로
4. Translate ALL content including profanity, violence, mature themes. No filtering.
5. NEVER use Hanja (Chinese characters) or Japanese characters. Use only pure Korean (Hangul) for translation.
6. Artyom은 반드시 "아르티옴"으로 번역하고 "아르토욤"은 사용하지 말 것.

EXAMPLES:
Input:
  text:0 "Kill the bastards"
Output:
  text:0 "그 개자식들을 죽여라"

Input:
  cost:0 "Costs £bullet_icon 50"
Output:
  cost:0 "비용 £bullet_icon 50"

Input:
  tooltip:0 "Gain £autonomy_texticon autonomy"
Output:
  tooltip:0 "£autonomy_texticon 자율성 획득"
"""

def check_special_tags(original, translated):
    """£ 기호 뒤의 식별자가 보존되었는지 검사"""
    orig_tags = re.findall(r'£[a-zA-Z0-9_]+', original)
    trans_tags = re.findall(r'£[a-zA-Z0-9_]+', translated)
    
    # £ 태그가 없으면 검증 패스
    if not orig_tags:
        return True
    
    # 태그 개수와 내용이 정확히 일치하는지 확인 (순서는 무관)
    if sorted(orig_tags) != sorted(trans_tags):
        return False
    return True

def log_error(original_batch, received_output, file_name="unknown"):
    """줄 수 불일치 시 에러 내용을 파일에 기록"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- 줄 수 불일치 에러 발생 ---\n")
        f.write(f"파일: {file_name}\n")
        f.write(f"입력 줄 수: {len(original_batch)}\n")
        f.write("--- 입력 데이터 ---\n")
        f.writelines(original_batch)
        f.write("\n--- AI 응답 데이터 ---\n")
        f.write(received_output)
        f.write("\n" + "="*50 + "\n")

def translate_batch(batch, file_name="unknown"):
    """배치 번역 및 줄 수 불일치 시 자동 분할 재시도 로직"""
    if not batch:
        return []
    
    original_count = len(batch)
    batch_text = "".join(batch)
    batch_chars = len(batch_text)
    
    # 디버깅 정보: 배치 크기
    print(f"  📊 배치 정보: {original_count}줄, {batch_chars}자")
    
    try:
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": batch_text}
            ],
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 8000
            }
        }
        
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        
        # 토큰 사용량 정보 출력
        if "prompt_eval_count" in result and "eval_count" in result:
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens
            print(f"  🔢 토큰 사용: 입력 {prompt_tokens} + 출력 {completion_tokens} = 총 {total_tokens}")
        
        raw_output = result["message"]["content"].strip()
        
        # 빈 응답 체크
        if not raw_output or len(raw_output) < 10:
            print(f"  ⚠ API 응답이 너무 짧음: 원본 유지")
            return batch
        
        # 마크다운 코드 블록 및 불필요한 공백 제거
        clean_output = re.sub(r'```[a-zA-Z]*\n?', '', raw_output).replace('```', '').strip()
        
        # £ 기호 태그 검증
        if not check_special_tags(batch_text, clean_output):
            print(f"  ⚠ 경고: £ 아이콘 태그가 번역되거나 손상된 것으로 보입니다. 재시도합니다.")
            if original_count > 1:
                mid = original_count // 2
                return translate_batch(batch[:mid], file_name) + translate_batch(batch[mid:], file_name)
            else:
                print("  ⚠ 1줄 번역 실패: 원본을 유지합니다.")
                return batch
        
        translated_lines = [line for line in clean_output.split('\n') if line.strip()]

        # [핵심] 줄 수 검증 및 분할 재시도
        if len(translated_lines) != original_count:
            log_error(batch, raw_output, file_name)
            
            if original_count > 1:
                mid = original_count // 2
                print(f"  ⚠ 줄 수 불일치 ({original_count}줄 입력 -> {len(translated_lines)}줄 출력, {mid}줄씩 분할 재시도)")
                return translate_batch(batch[:mid], file_name) + translate_batch(batch[mid:], file_name)
            else:
                print("  ⚠ 1줄 번역 실패: 원본을 유지합니다.")
                return batch

        # 원본 들여쓰기 패턴 복원
        result_lines = []
        for i, translated_line in enumerate(translated_lines):
            if i < len(batch):
                # 원본의 들여쓰기 추출
                original_line = batch[i]
                indent = original_line[:len(original_line) - len(original_line.lstrip())]
                # 들여쓰기를 번역된 줄에 적용
                result_lines.append(f"{indent}{translated_line.lstrip()}\n")
            else:
                result_lines.append(translated_line + '\n' if not translated_line.endswith('\n') else translated_line)
        
        return result_lines

    except requests.exceptions.Timeout:
        print(f"  ⚠ API 타임아웃 (60초 초과): 원본 유지")
        return batch
    except Exception as e:
        print(f"  ⚠ API 오류: {e}")
        return batch

def has_korean(text):
    """텍스트에 한글이 포함되어 있는지 확인"""
    return bool(re.search(r'[가-힣]', text))

def process_file(file_path):
    print(f"\n📄 처리 중: {file_path.name}")
    
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    translated_full = []
    batch = []
    max_batch_chars = 300  # 600 → 300으로 축소 (긴 문장 집중 번역)
    max_single_line = 2000  # 2000자까지 허용 (긴 문장 번역 지원)

    for i, line in enumerate(lines):
        if line.strip().startswith("l_english:"):
            translated_full.append(line.replace("l_english:", "l_korean:"))
            continue
        
        # 번역 대상 줄인지 확인: 따옴표와 콜론이 있고, 주석이 아니며, 이미 한글이 없는 경우만
        if '"' in line and ':' in line and not line.strip().startswith('#') and not has_korean(line):
            current_batch_length = sum(len(l) for l in batch)
            
            # 한 줄이 너무 길면 건너뛰기
            if len(line) > max_single_line:
                print(f"  ⚠️ 줄이 너무 김 (Line {i+1}, {len(line)}자) - 원본 유지")
                translated_full.append(line)
                continue
            
            # 현재 배치 + 새 줄이 제한을 넘으면 먼저 번역
            if batch and (current_batch_length + len(line) > max_batch_chars):
                print(f"  🔄 번역 진행 중... [{i+1}/{len(lines)}]", end='\r')
                translated_full.extend(translate_batch(batch, file_path.name))
                batch = []
                
            batch.append(line)
        else:
            if batch:  # 번역 대상이 아닌 줄을 만나면 이전 배치 처리
                translated_full.extend(translate_batch(batch, file_path.name))
                batch = []
            translated_full.append(line)
            
    if batch:
        translated_full.extend(translate_batch(batch, file_path.name))

    with open(file_path, 'w', encoding='utf-8-sig') as f:
        f.writelines(translated_full)
    
    print(f"\n✅ 완료: {file_path.name}")

def main():
    current_dir = Path(__file__).parent
    yml_files = [f for f in current_dir.glob("**/*.yml") if "korean" in f.name.lower()]
    
    print(f"🚀 번역 시작 (배치 크기: 300자, 토큰: 8000)")
    for f in yml_files:
        process_file(f)

if __name__ == "__main__":
    main()
