package com.floaq.pi.entity;

/** 관제 → Pi 하행 명령 (docs/api.md §3.5 · §4.4). */
public enum CommandType {
    /** 사고 종료 요청 */
    CLOSE_ACCIDENT,
    /** 영상 전송 중지 요청 */
    STOP_MEDIA
}
