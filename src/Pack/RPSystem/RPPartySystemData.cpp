#include "RPSystem/RPPartySystemData.h"
#include "types_pack.h"
#include <Pack/RPSystem.h>

#include <egg/core.h>

/**
 * @brief Constructor
 */
RPPartySystemData::RPPartySystemData() {
    reset();
}

/**
 * @brief Resets the data to a default save state
 */
void RPPartySystemData::reset() {
    for (int i = 0; i < OLD_DATA_LEN; i++) {
        mOldIndex[i] = -1;

        for (int j = 0; j < WPAD_ADDR_LEN; j++) {
            mOldAddress[i][j] = 0;
        }
    }

    mRegistTodayCount = 0;
    mRegistLastDate = 0;

    mGameFlags.makeAllZero();
    mGameFlags.set(1);
    mMsgFlags.makeAllZero();
}

/**
 * @brief Gets the old data for the specified player count and player index
 *
 * @param[out] pIndex Official database index
 * @param[out] pAddr Remote Bluetooth address
 * @param playerNum Player count
 * @param playerNo Player index
 */
void RPPartySystemData::getOldData(s8* pIndex, u8 pAddr[WPAD_ADDR_LEN],
                                    s32 playerNum, s32 playerNo) const {
    u32 rel2Abs[RP_MAX_PLAYERS] = {
        0,             // 1 player
        0 + 1,         // 2 players
    };

    u32 absIdx = rel2Abs[--playerNum] + playerNo;

    *pIndex = mOldIndex[absIdx];

    for (int i = 0; i < WPAD_ADDR_LEN; i++) {
        pAddr[i] = mOldAddress[absIdx][i];
    }
}

/**
 * @brief Sets the old data for the specified player count and player index
 *
 * @param[out] pIndex Official database index
 * @param[out] pAddr Remote Bluetooth address
 * @param playerNum Player count
 * @param playerNo Player index
 */
void RPPartySystemData::setOldData(s8 index, const u8 pAddr[WPAD_ADDR_LEN],
                                    s32 playerNum, s32 playerNo) {
    u32 rel2Abs[RP_MAX_PLAYERS] = {
        0,             // 1 player
        0 + 1,         // 2 players
    };

    u32 absIdx = rel2Abs[--playerNum] + playerNo;

    mOldIndex[absIdx] = index;

    for (int i = 0; i < WPAD_ADDR_LEN; i++) {
        mOldAddress[absIdx][i] = pAddr[i];
    }
}

/**
 * @brief Sets the amount of players registered today
 *
 * @param count Amount of players registered today
 */
void RPPartySystemData::setTodayDebutNum(u8 count) {
    mRegistTodayCount = count;
}
/**
 * @brief Gets the amount of players registered today
 */
u8 RPPartySystemData::getTodayDebutNum() const {
    return mRegistTodayCount;
}

/**
 * @brief Sets the last date a player was registered
 *
 * @param date Last registration date
 */
void RPPartySystemData::setPrevDebutDate(RPTime16 date) {
    mRegistLastDate = date;
}
/**
 * @brief Gets the last date a player was registered
 */
RPTime16 RPPartySystemData::getPrevDebutDate() const {
    return mRegistLastDate;
}

/**
 * @brief Sets whether the specified minigame is available
 *
 * @param idx Minigame index
 * @param open Whether the specified minigame is availible
 */
void RPPartySystemData::setGameOpen(s32 idx, bool open) {
    mGameFlags.changeBit(idx, open);
}

/**
 * @brief Tests whether the specified minigame is available
 *
 * @param idx Minigame index
 */
bool RPPartySystemData::isGameOpen(s32 idx) const {
    return mGameFlags.onBit(idx);
}

/**
 * @brief Sets whether a message was seen or not
 * 
 * @param idx Message index
 * @param seen Whether the message was seen or not
 */
void RPPartySystemData::setMsgSeen(u8 idx, bool seen) {
    mMsgFlags.changeBit(idx, seen);
}

/**
 * @brief Sets whether the specified minigame is available
 *
 * @param idx Minigame index
 * @param open Whether the specified minigame is availible
 */
bool RPPartySystemData::isMsgSeen(u8 idx) const {
    return mMsgFlags.onBit(idx);
}

/**
 * @brief Deserializes this object from the specified stream
 *
 * @param rStrm Memory stream
 */
void RPPartySystemData::read(EGG::RamStream& rStrm) {
    for (int i = 0; i < OLD_DATA_LEN; i++) {
        mOldIndex[i] = rStrm.read_s8();

        for (int j = 0; j < WPAD_ADDR_LEN; j++) {
            mOldAddress[i][j] = rStrm.read_u8();
        }
    }

    mRegistTodayCount = rStrm.read_u8();
    mRegistLastDate = rStrm.read_u16();
    mGameFlags = rStrm.read_u32();
    mMsgFlags = rStrm.read_u32();
}
/**
 * @brief Serializes this object to the specified stream
 *
 * @param rStrm Memory stream
 */
void RPPartySystemData::write(EGG::RamStream& rStrm) {
    for (int i = 0; i < OLD_DATA_LEN; i++) {
        rStrm.write_s8(mOldIndex[i]);

        for (int j = 0; j < WPAD_ADDR_LEN; j++) {
            rStrm.write_u8(mOldAddress[i][j]);
        }
    }

    rStrm.write_u8(mRegistTodayCount);
    rStrm.write_u16(mRegistLastDate);
    rStrm.write_u32(mGameFlags);
    rStrm.write_u32(mMsgFlags);
}
