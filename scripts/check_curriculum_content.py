"""Run from project root: python -m scripts.check_curriculum_content 1.1"""
import sys, hashlib
from services.curriculum_service import get_lesson, require_content
block=sys.argv[1] if len(sys.argv)>1 else '1.1'
row=get_lesson(block)
content, digest=require_content(row)
print('BLOCK:',row['block'])
print('TITLE (display only):',row['topic'])
print('CONTENT TYPE:',row.get('content_type'))
print('LESSON ORDER:',row.get('lesson_order'))
print('CONTENT CHARACTERS:',len(content))
print('CONTENT SHA256:',digest)
print('CONTENT PREVIEW:',content[:600])
print('This exact content string is the material sent to the lesson generator.')
