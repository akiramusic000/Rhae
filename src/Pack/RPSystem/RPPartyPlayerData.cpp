#include "RPSystem/RPPartyPlayerData.h"
#include <Pack/RPSystem.h>

/**
 * @brief Constructor
 */
RPPartyPlayerData::RPPartyPlayerData() {
    reset();
}

/**
 * @brief Resets the data to a default save state
 */
void RPPartyPlayerData::reset() {
    mPlayerFlags.makeAllZero();

    for (int i = 0; i < RFL_CREATEID_LEN; i++) {
        mCreateID.data[i] = 0;
    }

    mDebutTime = 0;

    for (int i = 0; i < EGame_Max; i++) {
        for (int j = 0; j < MY_RECORDS_LENGTH; j++) {
            mMyRecords[i][j] = 0;
        }

        mMedals[i] = EMedal_None;
    }

    mMedalDemoFlags.makeAllZero();
}

/**
 * @brief Gets a record for a specified game
 *
 * @param game Game index to get a record for
 * @param record Record index to get
 */
s32 RPPartyPlayerData::getRecord(EGame game, u32 record) const {
    return mMyRecords[game][record];
}
/**
 * @brief Sets a record for a specified game
 *
 * @param game Game index to set record for
 * @param record Record index to set
 */
void RPPartyPlayerData::setRecord(s32 newRecord, EGame game, u32 record) {
    mMyRecords[game][record] = newRecord;
}

/**
 * @brief Gets the medal achieved in a minigame
 *
 * @param game Game to get the medal for
 */
u8 RPPartyPlayerData::getMedal(EGame game) const {
    return mMedals[game];
}
/**
 * @brief Sets the medal achieved in a minigame
 *
 * @param medal Medal type to set to
 * @param game Minigame to set the medal for
 */
void RPPartyPlayerData::setMedal(u8 medal, EGame game) {
    mMedals[game] = medal;
}

/**
 * @brief Tests whether a player hasn't played a minigame yet
 */
bool RPPartyPlayerData::isFirstPlay() const {
    return mPlayerFlags.offBit(EFlag_FirstPlay);
}
/**
 * @brief Sets that a player has played a minigame
 */
void RPPartyPlayerData::setFirstPlay() {
    mPlayerFlags.setBit(EFlag_FirstPlay);
}

/**
 * @brief Gets whether a medal cutscene has played.
 *
 * @param cutscene Medal custscene
 */
bool RPPartyPlayerData::isMedalDemo(u8 cutscene) const {
    return mMedalDemoFlags.onBit(cutscene);
}
/**
 * @brief Sets whether a medal cutscene has played.
 *
 * @param cutscene Medal custscene
 * @param played Played status
 */
void RPPartyPlayerData::setMedalDemo(u8 cutscene) {
    mMedalDemoFlags.setBit(cutscene);
}

/**
 * @brief Tests whether this player has been registered with the player list
 */
bool RPPartyPlayerData::isRegistered() const {
    return mPlayerFlags.onBit(EFlag_Registered);
}

/**
 * @brief Sets whether this player has been registered with the player list
 *
 * @param registered Registration status
 */
void RPPartyPlayerData::setRegistered(bool registered) {
    mPlayerFlags.changeBit(EFlag_Registered, registered);
}

/**
 * @brief Gets this player's Mii create ID
 *
 * @param[out] pCreateID Mii create ID
 */
void RPPartyPlayerData::getCreateID(RFLCreateID* pCreateID) const {
    for (int i = 0; i < RFL_CREATEID_LEN; i++) {
        pCreateID->data[i] = mCreateID.data[i];
    }
}

/**
 * @brief Set this player's Mii create ID
 *
 * @param pCreateID Mii create ID
 */
void RPPartyPlayerData::setCreateID(const RFLCreateID* pCreateID) {
    for (int i = 0; i < RFL_CREATEID_LEN; i++) {
        mCreateID.data[i] = pCreateID->data[i];
    }
}

/**
 * @brief Gets the time this player was registered with the player list
 */
RPTime32 RPPartyPlayerData::getDebutTime() const {
    return mDebutTime;
}

/**
 * @brief Sets the time this player was registered with the player list
 *
 * @param time Debut time
 */
void RPPartyPlayerData::setDebutTime(RPTime32 time) {
    mDebutTime = time;
}

/**
 * @brief Deserializes this object from the specified stream
 *
 * @param rStrm Memory stream
 */
void RPPartyPlayerData::read(EGG::RamStream& rStrm) {
    mPlayerFlags = rStrm.read_u32();

    for (int i = 0; i < RFL_CREATEID_LEN; i++) {
        mCreateID.data[i] = rStrm.read_u8();
    }

    mDebutTime = rStrm.read_u32();

    for (int i = 0; i < EGame_Max; i++) {
        for (int j = 0; j < MY_RECORDS_LENGTH; j++) {
            mMyRecords[i][j] = rStrm.read_s32();
        }

        mMedals[i] = rStrm.read_u8();
    }

    mMedalDemoFlags = rStrm.read_u8();
}
/**
 * @brief Serializes this object to the specified stream
 *
 * @param rStrm Memory stream
 */
void RPPartyPlayerData::write(EGG::RamStream& rStrm) {
    rStrm.write_u32(mPlayerFlags);

    for (int i = 0; i < RFL_CREATEID_LEN; i++) {
        rStrm.write_u8(mCreateID.data[i]);
    }

    rStrm.write_u32(mDebutTime);

    for (int i = 0; i < EGame_Max; i++) {
        for (int j = 0; j < MY_RECORDS_LENGTH; j++) {
            rStrm.write_s32(mMyRecords[i][j]);
        }

        rStrm.write_u8(mMedals[i]);
    }

    rStrm.write_u8(mMedalDemoFlags);
}
