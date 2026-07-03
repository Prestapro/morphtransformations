"""Tests for dialogue_parser — scene headings, cast lists, false speaker lines."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dialogue_parser import (
    DialogueParser, _is_scene_heading, _is_cast_list,
    _is_stage_direction, _is_drama_speaker_candidate,
    detect_format, TextFormat, LineType,
)

KNOWN = {'Фамусов', 'Чацкий', 'София', 'Лиза', 'Скалозуб', 'Молчалин'}


class TestSceneHeading:
    """'Явление 8', 'Действие второе' etc. must not be speech."""
    
    def test_yavlenie_number(self):
        assert _is_scene_heading("Явление 8")
    
    def test_deystvie_word(self):
        assert _is_scene_heading("Действие второе")
    
    def test_act_roman(self):
        assert _is_scene_heading("Акт III")
    
    def test_prolog_solo(self):
        assert _is_scene_heading("Пролог")
    
    def test_epilog(self):
        assert _is_scene_heading("Эпилог.")
    
    def test_antrakt(self):
        assert _is_scene_heading("Антракт")
    
    def test_not_speaker(self):
        """Scene heading should NOT be speaker candidate."""
        assert not _is_drama_speaker_candidate("Явление 8")
    
    def test_speaker_still_works(self):
        """Regular speaker names should still work."""
        assert _is_drama_speaker_candidate("Фамусов", KNOWN)
    
    def test_negative_speech(self):
        """Regular speech should not be a scene heading."""
        assert not _is_scene_heading("Ну что ж, мой друг")
        assert not _is_scene_heading("Фамусов")


class TestCastList:
    """Comma-separated character names — stage direction, not speech."""
    
    def test_four_names(self):
        assert _is_cast_list("София, Лиза, Чацкий, Фамусов.", KNOWN)
    
    def test_two_names_with_parenthetical(self):
        line = "Фамусов, Чацкий (смотрит на дверь, в которую София вышла)."
        assert _is_cast_list(line, KNOWN)
    
    def test_with_conjunction(self):
        assert _is_cast_list("Те же и Скалозуб.", KNOWN)
    
    def test_single_name_negative(self):
        """Single name is NOT a cast list."""
        assert not _is_cast_list("Фамусов", KNOWN)
    
    def test_speech_negative(self):
        """Regular speech is NOT a cast list."""
        assert not _is_cast_list("Ну что ж, мой друг", KNOWN)
    
    def test_no_known_speakers(self):
        """Without known speakers, heuristic should still work for obvious cases."""
        assert _is_cast_list("Иван, Мария, Пётр.")


class TestStageDirection:
    """Combined stage direction detection."""
    
    def test_parenthetical(self):
        assert _is_stage_direction("(Останавливает часовую музыку.)")
    
    def test_brackets(self):
        assert _is_stage_direction("[Молчание.]")
    
    def test_scene_heading_as_stage(self):
        assert _is_stage_direction("Явление 8")
    
    def test_cast_list_as_stage(self):
        assert _is_stage_direction("София, Лиза, Чацкий, Фамусов.", KNOWN)
    
    def test_speaker_not_stage(self):
        assert not _is_stage_direction("Фамусов", KNOWN)


class TestFullParse:
    """Integration tests: full parse with known speakers."""
    
    def test_gore_ot_uma_scene(self):
        """Reproduce the original bug: 'Явление 8' must not appear as speech."""
        text = """Явление 8
София, Лиза, Чацкий, Фамусов.

Фамусов
Ну что ж, мой друг, ты не мог подойти?
Чацкий
Я поскакал бы к вам."""
        
        parser = DialogueParser(known_speakers=KNOWN)
        turns = parser.parse(text)
        
        # "Явление 8" and cast list should be stage_dirs, not speech
        all_speech = " ".join(t.full_speech() for t in turns)
        assert "Явление 8" not in all_speech
        assert "София, Лиза" not in all_speech
        
        # Фамусов and Чацкий should have their lines
        speakers = {t.speaker for t in turns}
        assert "Фамусов" in speakers
        assert "Чацкий" in speakers
    
    def test_cast_with_parenthetical(self):
        """Cast + parenthetical stage direction should be stage_dir."""
        text = """Фамусов
Ведь я его с Молчалиным не прогневал.

Фамусов, Чацкий (смотрит на дверь, в которую София вышла)."""
        
        parser = DialogueParser(known_speakers=KNOWN)
        turns = parser.parse(text)
        
        # The cast line should be stage_dir inside Фамусов's turn
        assert len(turns) == 1
        assert turns[0].speaker == "Фамусов"
        assert any("смотрит" in s for s in turns[0].stage_dirs)
    
    def test_prose_em_not_affected(self):
        """Prose with em-dash should still parse correctly."""
        text = """— Ты куда? — спросил Иван.
— Домой, — ответила Маша."""
        
        parser = DialogueParser()
        turns = parser.parse(text)
        
        speakers = {t.speaker for t in turns if t.speaker != "UNKNOWN"}
        assert "Иван" in speakers or "Маша" in speakers
