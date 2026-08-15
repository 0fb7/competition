"""EN/AR string table + RTL flag. Tkinter has no built-in bidi layout
engine, so RTL support here means: (1) every label routes through
`t(key)` so swapping `LANG` swaps every string, (2) `is_rtl()` tells
container widgets to mirror their pack/grid order and right-align text
when Arabic is active, (3) Arabic text is run through arabic_reshaper +
python-bidi before it reaches a Tk widget — Tk does not shape Arabic
glyphs (join letters into their contextual forms) or reorder them for
display on its own, so unshaped Arabic renders as disconnected, visually
backwards letters. `t()` returns display-ready text for either language.
Python code in the editor is always LTR regardless of UI language, per
spec section 30, and must NOT be passed through shape_ar().
"""

import arabic_reshaper
from bidi.algorithm import get_display

STRINGS = {
    "app_name": {"en": "CODE BATTLESHIP", "ar": "كود باتلشيب"},
    "competition": {"en": "Python Battle — Round 03", "ar": "معركة بايثون — الجولة 03"},
    "live": {"en": "LIVE", "ar": "مباشر"},
    "paused": {"en": "PAUSED", "ar": "إيقاف مؤقت"},
    "idle": {"en": "IDLE", "ar": "خامل"},
    "settings": {"en": "Settings", "ar": "الإعدادات"},
    "admin": {"en": "Administrator", "ar": "المسؤول"},

    "nav_dashboard": {"en": "Dashboard", "ar": "لوحة التحكم"},
    "nav_arena": {"en": "Battle Arena", "ar": "ساحة المعركة"},
    "nav_teams": {"en": "Teams", "ar": "الفرق"},
    "nav_code": {"en": "Python Code", "ar": "كود بايثون"},
    "nav_challenges": {"en": "Challenges", "ar": "التحديات"},
    "nav_competition": {"en": "Competition", "ar": "المسابقة"},
    "nav_leaderboard": {"en": "Leaderboard", "ar": "المتصدرون"},
    "nav_logs": {"en": "Battle Logs", "ar": "سجلات المعارك"},
    "nav_settings": {"en": "Settings", "ar": "الإعدادات"},

    "battle_arena": {"en": "Battle Arena", "ar": "ساحة المعركة"},
    "start": {"en": "Start Battle", "ar": "بدء المعركة"},
    "pause": {"en": "Pause", "ar": "إيقاف مؤقت"},
    "stop": {"en": "Stop", "ar": "إيقاف"},
    "reset": {"en": "Reset", "ar": "إعادة ضبط"},
    "open_arena_window": {"en": "Open Arena Window", "ar": "فتح نافذة الساحة"},

    "team": {"en": "Team", "ar": "الفريق"},
    "player": {"en": "Player", "ar": "اللاعب"},
    "ship": {"en": "Ship", "ar": "السفينة"},
    "score": {"en": "Score", "ar": "النقاط"},
    "health": {"en": "Health", "ar": "الصحة"},
    "energy": {"en": "Energy", "ar": "الطاقة"},
    "status": {"en": "Status", "ar": "الحالة"},
    "action": {"en": "Action", "ar": "الإجراء"},
    "active": {"en": "ACTIVE", "ar": "نشط"},
    "damaged": {"en": "DAMAGED", "ar": "متضرر"},
    "destroyed": {"en": "DESTROYED", "ar": "مدمر"},

    "difficulty": {"en": "Difficulty", "ar": "مستوى الصعوبة"},
    "level1": {"en": "Level 1 · Simple AI", "ar": "المستوى 1 · ذكاء بسيط"},
    "level2": {"en": "Level 2 · Intermediate Logic", "ar": "المستوى 2 · منطق متوسط"},
    "level3": {"en": "Level 3 · Advanced AI", "ar": "المستوى 3 · ذكاء متقدم"},
    "difficulty_note": {
        "en": "Configuration only — engine behavior does not change yet.",
        "ar": "إعداد فقط — لا يغيّر سلوك المحرك حالياً.",
    },

    "python_code": {"en": "Python Code", "ar": "كود بايثون"},
    "run": {"en": "Run", "ar": "تشغيل"},
    "validate": {"en": "Validate", "ar": "تحقق"},
    "submit": {"en": "Submit", "ar": "إرسال"},
    "running": {"en": "RUNNING", "ar": "قيد التشغيل"},
    "valid": {"en": "VALID", "ar": "صالح"},
    "invalid": {"en": "INVALID", "ar": "غير صالح"},

    "battle_log": {"en": "Battle Log", "ar": "سجل المعركة"},
    "leaderboard": {"en": "Leaderboard", "ar": "المتصدرون"},
    "rank": {"en": "Rank", "ar": "الترتيب"},
    "wins": {"en": "Wins", "ar": "الانتصارات"},
    "losses": {"en": "Losses", "ar": "الهزائم"},
    "damage": {"en": "Damage", "ar": "الضرر"},

    "teams_title": {"en": "Teams", "ar": "الفرق"},
    "team_name": {"en": "Team Name", "ar": "اسم الفريق"},
    "team_id": {"en": "Team ID", "ar": "معرّف الفريق"},
    "members": {"en": "Members", "ar": "الأعضاء"},
    "member_name": {"en": "Member name", "ar": "اسم العضو"},
    "create_team": {"en": "Create Team", "ar": "إنشاء فريق"},
    "edit_team": {"en": "Edit Team", "ar": "تعديل الفريق"},
    "delete_team": {"en": "Delete Team", "ar": "حذف الفريق"},
    "add_member": {"en": "Add Member", "ar": "إضافة عضو"},
    "remove_member": {"en": "Remove", "ar": "إزالة"},
    "not_ready": {"en": "NOT READY", "ar": "غير جاهز"},
    "in_battle": {"en": "IN BATTLE", "ar": "في المعركة"},
    "disabled_status": {"en": "DISABLED", "ar": "معطّل"},
    "save": {"en": "Save", "ar": "حفظ"},
    "cancel": {"en": "Cancel", "ar": "إلغاء"},
    "back": {"en": "Back", "ar": "رجوع"},
    "unassigned": {"en": "Unassigned", "ar": "غير مخصّص"},
    "assign_ship": {"en": "Assign Ship", "ar": "تعيين السفينة"},
    "damage_received": {"en": "Damage Received", "ar": "الضرر المستقبل"},
    "ship_change_pending_reset": {
        "en": "This change will take effect after the current battle is reset.",
        "ar": "سيصبح هذا التغيير سارياً بعد إعادة تعيين المعركة الحالية.",
    },
    "no_teams_title": {"en": "No teams yet.", "ar": "لا توجد فرق بعد."},
    "no_teams_body": {
        "en": "Create your first team to begin the competition.",
        "ar": "أنشئ أول فريق لبدء المنافسة.",
    },
    "confirm_delete_title": {"en": "Delete Team?", "ar": "حذف الفريق؟"},
    "confirm_delete_body": {
        "en": "This action cannot be undone.", "ar": "لا يمكن التراجع عن هذا الإجراء.",
    },
    "cannot_delete_active": {
        "en": "Team cannot be deleted while participating in an active battle.",
        "ar": "لا يمكن حذف الفريق أثناء مشاركته في معركة نشطة.",
    },
    "error_duplicate_id": {"en": "That Team ID is already in use.", "ar": "معرّف الفريق هذا مستخدم بالفعل."},
    "error_empty_name": {"en": "Team name cannot be empty.", "ar": "لا يمكن أن يكون اسم الفريق فارغاً."},
    "error_empty_id": {"en": "Team ID cannot be empty.", "ar": "لا يمكن أن يكون معرّف الفريق فارغاً."},
    "error_invalid_id": {
        "en": "Team ID may only contain letters, numbers, - and _.",
        "ar": "يجب أن يحتوي معرّف الفريق على أحرف وأرقام و- و_ فقط.",
    },
    "error_ship_taken": {"en": "That ship is already assigned to another team.", "ar": "هذه السفينة معيّنة لفريق آخر بالفعل."},
    "error_generic": {"en": "Something went wrong. Please try again.", "ar": "حدث خطأ ما. حاول مرة أخرى."},
    "details": {"en": "Details", "ar": "التفاصيل"},
    "member_count": {"en": "Members", "ar": "الأعضاء"},

    "challenges_title": {"en": "Challenges", "ar": "التحديات"},
    "challenge_name": {"en": "Challenge Name", "ar": "اسم التحدي"},
    "challenge_id": {"en": "Challenge ID", "ar": "معرّف التحدي"},
    "description": {"en": "Description", "ar": "الوصف"},
    "objective": {"en": "Objective", "ar": "الهدف"},
    "time_limit": {"en": "Time Limit", "ar": "الحد الزمني"},
    "win_condition": {"en": "Win Condition", "ar": "شرط الفوز"},
    "rules": {"en": "Rules", "ar": "القواعد"},
    "allowed_api": {"en": "Allowed API", "ar": "واجهة البرمجة المسموح بها"},
    "create_challenge": {"en": "Create Challenge", "ar": "إنشاء تحدي"},
    "edit_challenge": {"en": "Edit Challenge", "ar": "تعديل التحدي"},
    "delete_challenge": {"en": "Delete Challenge", "ar": "حذف التحدي"},
    "draft": {"en": "DRAFT", "ar": "مسودة"},
    "archived": {"en": "ARCHIVED", "ar": "مؤرشف"},
    "activate": {"en": "Activate", "ar": "تفعيل"},
    "activated": {"en": "Active challenge", "ar": "التحدي النشط"},
    "no_time_limit": {"en": "No time limit", "ar": "بدون حد زمني"},
    "seconds_short": {"en": "s", "ar": "ث"},
    "win_destroy_enemy": {"en": "Destroy enemy ship", "ar": "تدمير سفينة العدو"},
    "win_time_limit_draw": {"en": "Time limit -> draw", "ar": "الحد الزمني ← تعادل"},

    "rule_movement_speed": {"en": "Movement Speed", "ar": "سرعة الحركة"},
    "rule_attack_enabled": {"en": "Attacks Enabled", "ar": "تفعيل الهجوم"},
    "rule_attack_range": {"en": "Attack Range", "ar": "مدى الهجوم"},
    "rule_attack_damage": {"en": "Damage", "ar": "الضرر"},
    "rule_attack_cooldown": {"en": "Cooldown", "ar": "فترة التهدئة"},
    "rule_energy_pool": {"en": "Energy Pool", "ar": "مخزون الطاقة"},
    "rule_sensor_range": {"en": "Sensor Range", "ar": "مدى الاستشعار"},
    "rule_battle_duration": {"en": "Battle Duration (s)", "ar": "مدة المعركة (ث)"},

    "no_challenges_title": {"en": "No challenges yet.", "ar": "لا توجد تحديات بعد."},
    "no_challenges_body": {
        "en": "Create a challenge to configure a competition.",
        "ar": "أنشئ تحدياً لإعداد منافسة.",
    },
    "confirm_delete_challenge_title": {"en": "Delete Challenge?", "ar": "حذف التحدي؟"},
    "cannot_delete_active_challenge": {
        "en": "An active Challenge cannot be deleted. Deactivate it first.",
        "ar": "لا يمكن حذف تحدٍ نشط. قم بإلغاء تفعيله أولاً.",
    },
    "cannot_edit_active_rules": {
        "en": "Rules, difficulty, win condition and allowed API cannot be changed while this Challenge is active.",
        "ar": "لا يمكن تغيير القواعد أو الصعوبة أو شرط الفوز أو واجهة البرمجة أثناء نشاط هذا التحدي.",
    },
    "error_empty_description": {"en": "Description cannot be empty.", "ar": "لا يمكن أن يكون الوصف فارغاً."},
    "error_empty_challenge_name": {"en": "Challenge name cannot be empty.", "ar": "لا يمكن أن يكون اسم التحدي فارغاً."},
    "error_empty_challenge_id": {"en": "Challenge ID cannot be empty.", "ar": "لا يمكن أن يكون معرّف التحدي فارغاً."},
    "error_invalid_challenge_id": {
        "en": "Challenge ID may only contain letters, numbers, - and _.",
        "ar": "يجب أن يحتوي معرّف التحدي على أحرف وأرقام و- و_ فقط.",
    },
    "error_duplicate_challenge_id": {"en": "That Challenge ID is already in use.", "ar": "معرّف التحدي هذا مستخدم بالفعل."},
    "error_invalid_difficulty": {"en": "Choose a valid difficulty level.", "ar": "اختر مستوى صعوبة صالحاً."},
    "error_invalid_win_condition": {"en": "Choose a valid win condition.", "ar": "اختر شرط فوز صالحاً."},
    "error_invalid_rule": {"en": "One or more rule values are invalid.", "ar": "قيمة واحدة أو أكثر من القواعد غير صالحة."},

    "submissions_title": {"en": "Submissions", "ar": "التسليمات"},
    "submission": {"en": "Submission", "ar": "التسليم"},
    "version": {"en": "Version", "ar": "الإصدار"},
    "validated": {"en": "VALIDATED", "ar": "تم التحقق"},
    "submitted": {"en": "SUBMITTED", "ar": "تم التسليم"},
    "rejected": {"en": "REJECTED", "ar": "مرفوض"},
    "test": {"en": "Test", "ar": "اختبار"},
    "new_version": {"en": "New Version", "ar": "إصدار جديد"},
    "read_only": {"en": "Read Only", "ar": "للقراءة فقط"},
    "submission_history": {"en": "Submission History", "ar": "سجل التسليمات"},
    "validation_errors": {"en": "Validation Errors", "ar": "أخطاء التحقق"},
    "test_results": {"en": "Test Results", "ar": "نتائج الاختبار"},
    "select_team": {"en": "Select a team.", "ar": "اختر فريقاً."},
    "open_python_code_tab": {
        "en": "Editing moved to the Python Code tab — team submissions are versioned there.",
        "ar": "انتقل التحرير إلى تبويب كود بايثون — تُدار إصدارات الفرق هناك.",
    },
    "select_challenge": {"en": "Select a challenge.", "ar": "اختر تحدياً."},
    "no_submissions_title": {"en": "No submissions yet.", "ar": "لا توجد تسليمات بعد."},
    "no_submissions_body": {
        "en": "Create your first version to begin.",
        "ar": "أنشئ أول إصدار للبدء.",
    },
    "validation_failed": {"en": "Validation failed.", "ar": "فشل التحقق."},
    "validation_passed": {"en": "Validation passed.", "ar": "نجح التحقق."},
    "test_passed": {"en": "Test passed.", "ar": "نجح الاختبار."},
    "test_failed": {"en": "Test failed.", "ar": "فشل الاختبار."},
    "submitted_read_only": {"en": "Submitted — Read Only.", "ar": "تم التسليم — للقراءة فقط."},
    "draft_editable": {"en": "Draft — Editable.", "ar": "مسودة — قابلة للتعديل."},
    "active_version": {"en": "Active", "ar": "نشط"},
    "testing_in_progress": {"en": "Testing...", "ar": "جارٍ الاختبار..."},
    "submit_blocked_validation": {
        "en": "Cannot submit: validation failed. Fix the errors below and try again.",
        "ar": "لا يمكن التسليم: فشل التحقق. أصلح الأخطاء أدناه وحاول مرة أخرى.",
    },
    "submit_blocked_test": {
        "en": "Cannot submit: the test did not pass. Review the test results below.",
        "ar": "لا يمكن التسليم: لم ينجح الاختبار. راجع نتائج الاختبار أدناه.",
    },
    "winner": {"en": "Winner", "ar": "الفائز"},
    "duration": {"en": "Duration", "ar": "المدة"},
    "final_hp": {"en": "Final HP", "ar": "الصحة النهائية"},
    "events": {"en": "Events", "ar": "الأحداث"},
    "line": {"en": "Line", "ar": "السطر"},

    "competition_title": {"en": "Competition", "ar": "المسابقة"},
    "competitions_title": {"en": "Competitions", "ar": "المسابقات"},
    "competition_name": {"en": "Competition Name", "ar": "اسم المسابقة"},
    "competition_id": {"en": "Competition ID", "ar": "معرّف المسابقة"},
    "create_competition": {"en": "Create Competition", "ar": "إنشاء مسابقة"},
    "edit_competition": {"en": "Edit Competition", "ar": "تعديل المسابقة"},
    "delete_competition": {"en": "Delete Competition", "ar": "حذف المسابقة"},
    "start_competition": {"en": "Start Competition", "ar": "بدء المسابقة"},
    "pause_competition": {"en": "Pause Competition", "ar": "إيقاف المسابقة مؤقتاً"},
    "resume_competition": {"en": "Resume", "ar": "استئناف"},
    "complete_competition": {"en": "Complete Competition", "ar": "إنهاء المسابقة"},
    "mark_ready": {"en": "Mark Ready", "ar": "تعليم كجاهز"},
    "round": {"en": "Round", "ar": "الجولة"},
    "rounds": {"en": "Rounds", "ar": "الجولات"},
    "match": {"en": "Match", "ar": "المباراة"},
    "matches": {"en": "Matches", "ar": "المباريات"},
    "participants": {"en": "Participants", "ar": "المشاركون"},
    "add_team": {"en": "Add Team", "ar": "إضافة فريق"},
    "remove_team": {"en": "Remove", "ar": "إزالة"},
    "start_round": {"en": "Start Round", "ar": "بدء الجولة"},
    "start_match": {"en": "Start Match", "ar": "بدء المباراة"},
    "create_round": {"en": "Create Round", "ar": "إنشاء جولة"},
    "round_robin": {"en": "Round Robin", "ar": "الدوري"},
    "single_elimination": {"en": "Single Elimination", "ar": "إقصاء مباشر"},
    "custom_round": {"en": "Custom", "ar": "مخصّصة"},
    "generate_matches": {"en": "Generate Matches", "ar": "توليد المباريات"},
    "pending": {"en": "PENDING", "ar": "قيد الانتظار"},
    "completed": {"en": "COMPLETED", "ar": "مكتملة"},
    "cancelled": {"en": "CANCELLED", "ar": "ملغاة"},
    "error_status": {"en": "ERROR", "ar": "خطأ"},
    "bye": {"en": "BYE", "ar": "إعفاء"},
    "draw": {"en": "DRAW", "ar": "تعادل"},
    "team_a": {"en": "Team A", "ar": "الفريق أ"},
    "team_b": {"en": "Team B", "ar": "الفريق ب"},
    "vs": {"en": "VS", "ar": "ضد"},
    "advances": {"en": "advances", "ar": "يتأهل"},
    "challenge_label": {"en": "Challenge", "ar": "التحدي"},
    "no_competitions_title": {"en": "No competitions yet.", "ar": "لا توجد مسابقات بعد."},
    "no_competitions_body": {
        "en": "Create a competition to organize teams into rounds and matches.",
        "ar": "أنشئ مسابقة لتنظيم الفرق في جولات ومباريات.",
    },
    "confirm_delete_competition_title": {"en": "Delete Competition?", "ar": "حذف المسابقة؟"},
    "cannot_delete_active_competition": {
        "en": "An active competition cannot be deleted. Pause or complete it first.",
        "ar": "لا يمكن حذف مسابقة نشطة. أوقفها مؤقتاً أو أكملها أولاً.",
    },
    "cannot_delete_historical_competition": {
        "en": "This competition has completed match history and cannot be deleted.",
        "ar": "تحتوي هذه المسابقة على سجل مباريات مكتمل ولا يمكن حذفها.",
    },
    "cannot_edit_locked_structure": {
        "en": "Challenge and participating teams cannot be changed once the competition is no longer a draft.",
        "ar": "لا يمكن تغيير التحدي أو الفرق المشاركة بعد أن تصبح المسابقة غير مسودة.",
    },
    "error_not_enough_teams": {"en": "Add at least 2 eligible teams before marking ready.", "ar": "أضف فريقين مؤهلين على الأقل قبل التعليم كجاهز."},
    "error_team_not_eligible": {
        "en": "This team has no submitted version for the selected Challenge.",
        "ar": "لا يوجد إصدار تم تسليمه لهذا الفريق ضمن التحدي المحدد.",
    },
    "error_team_already_added": {"en": "This team is already in the competition.", "ar": "هذا الفريق مضاف بالفعل إلى المسابقة."},
    "error_team_disabled": {"en": "This team is disabled.", "ar": "هذا الفريق معطّل."},
    "error_no_rounds": {"en": "Create at least one round before starting.", "ar": "أنشئ جولة واحدة على الأقل قبل البدء."},
    "match_not_eligible": {"en": "This match cannot start yet.", "ar": "لا يمكن بدء هذه المباراة الآن."},
    "competition_context": {"en": "Competition Match", "ar": "مباراة المسابقة"},
    "winner_advances": {"en": "advances to the next round", "ar": "يتأهل إلى الجولة التالية"},
    "cancel_match": {"en": "Cancel Match", "ar": "إلغاء المباراة"},
    "confirm_cancel_match": {"en": "Cancel this match?", "ar": "هل تريد إلغاء هذه المباراة؟"},

    "nav_results": {"en": "Results", "ar": "النتائج"},
    "results_title": {"en": "Results & History", "ar": "النتائج والسجل"},
    "history_title": {"en": "History", "ar": "السجل"},
    "match_history_title": {"en": "Match History", "ar": "سجل المباريات"},
    "match_details_title": {"en": "Match Details", "ar": "تفاصيل المباراة"},
    "competition_summary": {"en": "Competition Summary", "ar": "ملخص المسابقة"},
    "champion": {"en": "Champion", "ar": "البطل"},
    "no_champion_yet": {"en": "Not yet decided", "ar": "لم يُحدَّد بعد"},
    "total_teams": {"en": "Total Teams", "ar": "إجمالي الفرق"},
    "total_matches": {"en": "Total Matches", "ar": "إجمالي المباريات"},
    "completed_matches": {"en": "Completed Matches", "ar": "المباريات المكتملة"},
    "matches_played": {"en": "Matches Played", "ar": "المباريات الملعوبة"},
    "win_rate": {"en": "Win Rate", "ar": "نسبة الفوز"},
    "damage_dealt": {"en": "Damage Dealt", "ar": "الضرر المسبب"},
    "avg_duration": {"en": "Avg. Duration", "ar": "متوسط المدة"},
    "hp_remaining": {"en": "HP Remaining", "ar": "الصحة المتبقية"},
    "view_details": {"en": "View Details", "ar": "عرض التفاصيل"},
    "recent_matches": {"en": "Recent Matches", "ar": "المباريات الأخيرة"},
    "battle_timeline": {"en": "Battle Timeline", "ar": "الخط الزمني للمعركة"},
    "round_standings": {"en": "Round Standings", "ar": "ترتيب الجولة"},
    "advanced_teams": {"en": "Advanced", "ar": "المتأهلون"},
    "select_competition": {"en": "Select a competition.", "ar": "اختر مسابقة."},
    "all_competitions": {"en": "All Competitions", "ar": "كل المسابقات"},
    "all_teams": {"en": "All Teams", "ar": "كل الفرق"},
    "all_results": {"en": "All Results", "ar": "كل النتائج"},
    "filter_competition": {"en": "Competition", "ar": "المسابقة"},
    "filter_team": {"en": "Team", "ar": "الفريق"},
    "filter_result": {"en": "Result", "ar": "النتيجة"},
    "clear_filters": {"en": "Clear Filters", "ar": "مسح الفلاتر"},
    "no_results_title": {"en": "No completed matches yet.", "ar": "لا توجد مباريات مكتملة بعد."},
    "no_results_body": {
        "en": "Results appear here once a competition match finishes.",
        "ar": "تظهر النتائج هنا بمجرد انتهاء إحدى مباريات المسابقة.",
    },
    "no_events_recorded": {"en": "No events recorded for this match.", "ar": "لا توجد أحداث مسجّلة لهذه المباراة."},
    "bye_no_battle": {"en": "Bye — no battle was played.", "ar": "إعفاء — لم تُلعب أي معركة."},

    "nav_live_monitor": {"en": "Live Monitoring", "ar": "المراقبة المباشرة"},
    "live_monitoring_title": {"en": "Live Monitoring", "ar": "المراقبة المباشرة"},
    "preparing": {"en": "PREPARING", "ar": "قيد التحضير"},
    "stopped": {"en": "STOPPED", "ar": "متوقف"},
    "resume": {"en": "Resume", "ar": "استئناف"},
    "confirm_reset_match": {"en": "Reset current match?", "ar": "هل تريد إعادة تعيين المباراة الحالية؟"},
    "confirm_stop_match": {"en": "Stop the current match?", "ar": "هل تريد إيقاف المباراة الحالية؟"},

    "competition_status_title": {"en": "Competition Status", "ar": "حالة المسابقة"},
    "current_match_label": {"en": "Current Match", "ar": "المباراة الحالية"},
    "matches_remaining": {"en": "Remaining Matches", "ar": "المباريات المتبقية"},
    "match_queue": {"en": "Match Queue", "ar": "طابور المباريات"},
    "current": {"en": "CURRENT", "ar": "الحالية"},
    "next_match": {"en": "NEXT", "ar": "التالية"},
    "upcoming": {"en": "UPCOMING", "ar": "القادمة"},

    "live_match_monitor": {"en": "Live Match Monitor", "ar": "مراقبة المباراة المباشرة"},
    "no_active_match": {"en": "No active match", "ar": "لا توجد مباراة نشطة"},
    "remaining_time": {"en": "Remaining", "ar": "المتبقي"},
    "position": {"en": "Position", "ar": "الموقع"},
    "attack_cooldown_label": {"en": "Cooldown", "ar": "فترة التهدئة"},
    "current_target": {"en": "Current Target", "ar": "الهدف الحالي"},

    "engine_health_title": {"en": "Engine Health", "ar": "حالة المحرك"},
    "engine_status_label": {"en": "Engine Status", "ar": "حالة المحرك"},
    "runner_status_label": {"en": "Runner Status", "ar": "حالة المشغّل"},
    "thread_status_label": {"en": "Thread Status", "ar": "حالة العملية"},
    "fps": {"en": "FPS", "ar": "إطار/ثانية"},
    "tick_count": {"en": "Tick Count", "ar": "عدد الدورات"},
    "simulation_time": {"en": "Simulation Time", "ar": "زمن المحاكاة"},
    "ui_update_rate": {"en": "UI Update Rate", "ar": "معدل تحديث الواجهة"},
    "last_event": {"en": "Last Event", "ar": "آخر حدث"},
    "last_event_time": {"en": "Last Event Time", "ar": "وقت آخر حدث"},

    "event_stream_title": {"en": "Live Event Stream", "ar": "تدفق الأحداث المباشر"},
    "alerts_title": {"en": "Alerts", "ar": "التنبيهات"},
    "alert_team_code_error": {"en": "Team code error", "ar": "خطأ في كود الفريق"},
    "alert_match_completed": {"en": "Match completed", "ar": "اكتملت المباراة"},
    "alert_match_draw": {"en": "Match ended in a draw", "ar": "انتهت المباراة بالتعادل"},
    "alert_engine_stopped": {"en": "Engine stopped", "ar": "توقف المحرك"},
    "alert_match_cannot_start": {"en": "Match cannot start", "ar": "لا يمكن بدء المباراة"},
    "alert_team_code_timeout": {"en": "Team code timed out", "ar": "انتهت مهلة كود الفريق"},
    "timeout_status": {"en": "TIMEOUT", "ar": "انتهت المهلة"},
    "acknowledge_error": {"en": "Acknowledge", "ar": "الإقرار"},

    "system_status": {"en": "System Status", "ar": "حالة النظام"},
    "simulation_engine": {"en": "Simulation Engine", "ar": "محرك المحاكاة"},
    "python_runtime": {"en": "Python Runtime", "ar": "بيئة بايثون"},
    "code_validation": {"en": "Code Validation", "ar": "التحقق من الكود"},
    "battle_server": {"en": "Battle Server", "ar": "خادم المعركة"},
    "online": {"en": "ONLINE", "ar": "متصل"},
    "ready": {"en": "READY", "ar": "جاهز"},
    "passed": {"en": "PASSED", "ar": "ناجح"},
    "connected": {"en": "CONNECTED", "ar": "متصل"},
    "not_available": {"en": "N/A", "ar": "غير متوفر"},
}

_lang = {"code": "en"}


def set_lang(code: str) -> None:
    if code not in ("en", "ar"):
        raise ValueError(code)
    _lang["code"] = code


def get_lang() -> str:
    return _lang["code"]


def is_rtl() -> bool:
    return _lang["code"] == "ar"


def shape_ar(text: str) -> str:
    """Reshapes + bidi-reorders raw Arabic text for display in Tk widgets."""
    return get_display(arabic_reshaper.reshape(text))


def t(key: str) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    raw = entry.get(_lang["code"], entry["en"])
    if _lang["code"] == "ar":
        return shape_ar(raw)
    return raw
