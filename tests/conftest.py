import os

# 테스트는 저장된 Studio A, B 결과와 상관없이 샘플 입력으로 돌린다.
os.environ.setdefault("LNG_IGNORE_STUDIO", "1")
