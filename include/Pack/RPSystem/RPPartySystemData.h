#ifndef RP_SYSTEM_PARTY_SYSTEM_DATA_H
#define RP_SYSTEM_PARTY_SYSTEM_DATA_H
#include <Pack/types_pack.h>

#include <egg/core.h>

#include <revolution/WPAD.h>

//! @addtogroup rp_system
//! @{

/**
 * @brief Party Pack save file system data
 */
class RPPartySystemData {
public:
    /**
     * @brief Minigame ID
     */
    enum EGame {
        EGame_Duc, //!< Shooting Range
        EGame_Wly, //!< Find Mii
        EGame_Pnp, //!< Table Tennis
        EGame_Bom, //!< Pose Mii
        EGame_Hky, //!< Laser Hockey
        EGame_Bil, //!< Billiards
        EGame_Fsh, //!< Fishing
        EGame_Cow, //!< Charge!
        EGame_Tnk, //!< Tanks!

        EGame_Max,
    };

    /**
     * @brief Message ID
     */
    enum EMsg {
        EMsg_Welcome,    //!< Play for the first time
        EMsg_StageTwo,   //!< Unlock stage two
        EMsg_StageThree, //!< Unlock stage three
        EMsg_StageFour,  //!< Unlock stage four
        EMsg_StageFive,  //!< Unlock stage five
        EMsg_StageSix,   //!< Unlock stage six
        EMsg_StageSeven, //!< Unlock stage seven
        EMsg_StageEight, //!< Unlock stage eight
        EMsg_StageFinal, //!< Unlock the final stage
        EMsg_Master,     //!< Completed all stages

        EMsg_Max
    };

    //! Old data exists for each player count
    static const int OLD_DATA_LEN = 1 + 2;

public:
    /**
     * @brief Constructor
     */
    RPPartySystemData();

    /**
     * @brief Resets the data to a default save state
     */
    void reset();

    /**
     * @brief Gets the old data for the specified player count and player index
     *
     * @param[out] pIndex Official database index
     * @param[out] pAddr Remote Bluetooth address
     * @param playerNum Player count
     * @param playerNo Player index
     */
    void getOldData(s8* pIndex, u8 pAddr[WPAD_ADDR_LEN], s32 playerNum,
                    s32 playerNo) const;
    /**
     * @brief Sets the old data for the specified player count and player index
     *
     * @param[out] pIndex Official database index
     * @param[out] pAddr Remote Bluetooth address
     * @param playerNum Player count
     * @param playerNo Player index
     */
    void setOldData(s8 index, const u8 pAddr[WPAD_ADDR_LEN], s32 playerNum,
                    s32 playerNo);

    /**
     * @brief Sets the amount of players registered today
     *
     * @param count Amount of players registered today
     */
    void setTodayDebutNum(u8 count);
    /**
     * @brief Gets the amount of players registered today
     */
    u8 getTodayDebutNum() const;

    /**
     * @brief Sets the last date a player was registered
     *
     * @param date Last registration date
     */
    void setPrevDebutDate(RPTime16 date);
    /**
     * @brief Gets the last date a player was registered
     */
    RPTime16 getPrevDebutDate() const;

    /**
     * @brief Sets whether the specified minigame is available
     *
     * @param idx Minigame index
     * @param open Whether the specified minigame is availible
     */
    void setGameOpen(s32 idx, bool open);

    /**
     * @brief Tests whether the specified minigame is available
     *
     * @param idx Minigame index
     */
    bool isGameOpen(s32 idx) const;

    /**
     * @brief Sets whether a message was seen or not
     * 
     * @param idx Message index
     * @param seen Whether the message was seen or not
     */
    void setMsgSeen(u8 idx, bool seen);

    /**
     * @brief Tests whether a message was seen or not
     * 
     * @param idx Message index
     */
    bool isMsgSeen(u8 idx) const;

    /**
     * @brief Deserializes this object from the specified stream
     *
     * @param rStrm Memory stream
     */
    void read(EGG::RamStream& rStrm);
    /**
     * @brief Serializes this object to the specified stream
     *
     * @param rStrm Memory stream
     */
    void write(EGG::RamStream& rStrm);

private:
    /**
     * @name Previous Mii data
     */
    /**@{*/
    //! Official database index
    s8 mOldIndex[OLD_DATA_LEN]; // at 0x0
    //! Remote Blutetooth address
    u8 mOldAddress[OLD_DATA_LEN][WPAD_ADDR_LEN]; // at 0x3
    /**@}*/

    //! Number of new players registered today
    u8 mRegistTodayCount; // at 0x15
    //! Last player registered
    RPTime16 mRegistLastDate; // at 0x16

    //! Game unlock flags
    EGG::TBitFlag<u32> mGameFlags; // at 0x18
    //! Message seen flags
    EGG::TBitFlag<u32> mMsgFlags; // at 0x1C
};

//! @}

#endif
