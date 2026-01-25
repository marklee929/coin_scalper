import os
import subprocess
from datetime import date
from utils.logger import logger  # 로거 사용

# 날짜 자동 설정
if __name__ == '__main__':
    today = date.today().isoformat().replace('-', '')
    data_root = f"./crawling/{today}"
    try:
        csv_files = [f for f in os.listdir(data_root) if f.endswith('_5min.csv')]
    except Exception as e:
        logger.error(f"크롤링 데이터 폴더 조회 실패: {e}")
        csv_files = []

    logger.info(f"🧠 총 {len(csv_files)}개 종목 학습 시작...")

    # 학습 스크립트 경로
    script_path = os.path.abspath("PatchTST/PatchTST_supervised/run_longExp.py")

    for file in csv_files:
        code_id = file.replace('_5min.csv', '')
        model_id = f"{code_id}_5min"

        logger.info(f"🚀 학습 시작: {file} → 모델 ID: {model_id}")

        cmd = [
            'python', script_path,
            '--is_training', '1',
            '--root_path', data_root,
            '--data_path', file,
            '--model_id', model_id,
            '--model', 'PatchTST',
            '--data', 'custom',
            '--features', 'M',
            '--seq_len', '60',
            '--label_len', '30',
            '--pred_len', '12',
            '--e_layers', '2',
            '--d_model', '64',
            '--n_heads', '4',
            '--patch_len', '24',
            '--stride', '12',
            '--des', 'batch-scalping',
            '--itr', '1',
            '--num_workers', '0',
        ]

        # PYTHONPATH 환경 변수에 PatchTST 프로젝트 루트 추가
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.abspath('PatchTST')

        try:
            subprocess.run(cmd, env=env, check=True)
            logger.info(f"✅ 완료: {file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ 학습 실패: {file} (exit {e.returncode})")
        except Exception as e:
            logger.error(f"❌ 예외 발생 during 학습: {file} -> {e}")

    logger.info("🎉 전체 학습 완료!")
