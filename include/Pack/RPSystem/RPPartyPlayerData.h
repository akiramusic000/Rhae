#ifndef RP_SYSTEM_PARTY_PLAYER_DATA_H
#define RP_SYSTEM_PARTY_PLAYER_DATA_H
#include <Pack/types_pack.h>

#include <RVLFaceLib.h>

#include <egg/core.h>

//! @addtogroup rp_system
//! @{

/**
 * @brief Party Pack save file player data
 */
class RPPartyPlayerData {
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
     * @brief Medal type
     */
    enum EMedal {
        EMedal_None,
        EMedal_Bronze,
        EMedal_Silver,
        EMedal_Gold,
        EMedal_Platinum,
    };

    /**
     * @brief Medal cutscene ID
     */
    enum EMedalDemo {
        EMedalDemo_0,
        EMedalDemo_BronzeComplete,  //!< All bronze medals earned
        EMedalDemo_SilverComplete,  //!< All silver medals earned
        EMedalDemo_GoldComplete,    //!< All gold medals earned
        EMedalDemo_PlatinumComplete //!< All platinum medals earned
    };

    //! Number of sports in the My Records leaderboard
    static const int MY_RECORDS_LENGTH = 5;

public:
    /**
     * @brief Constructor
     */
    RPPartyPlayerData();

    /**
     * @brief Resets the data to a default save state
     */
    void reset();

    /**
     * @brief Gets a record for a specified game
     *
     * @param game Game index to get a record for
     * @param record Record index to get
     */
    s32 getRecord(EGame game, u32 record) const;
    /**
     * @brief Sets a record for a specified game
     *
     * @param game Game index to set record for
     * @param record Record index to set
     */
    void setRecord(s32 newRecord, EGame game, u32 record);

    /**
     * @brief Gets the medal achieved in a minigame
     *
     * @param game Game to get the medal for
     */
    u8 getMedal(EGame game) const;
    /**
     * @brief Sets the medal achieved in a minigame
     *
     * @param medal Medal type to set to
     * @param game Minigame to set the medal for
     */
    void setMedal(u8 medal, EGame game);

    /**
     * @brief Tests whether a player hasn't played a minigame yet
     */
    bool isFirstPlay() const;
    /**
     * @brief Sets that a player has played a minigame
     */
    void setFirstPlay();

    /**
     * @brief Gets whether a medal cutscene has played
     *
     * @param cutscene Medal custscene
     */
    bool isMedalDemo(u8 cutscene) const;
    /**
     * @brief Sets a medal cutscene to played
     *
     * @param cutscene Medal custscene
     */
    void setMedalDemo(u8 cutscene);

    /**
     * @name Player list
     */
    /**@{*/
    /**
     * @brief Tests whether this player has been registered with the player list
     */
    bool isRegistered() const;
    /**
     * @brief Sets whether this player has been registered with the player list
     *
     * @param registered Registration status
     */
    void setRegistered(bool registered);

    /**
     * @brief Gets this player's Mii create ID
     *
     * @param[out] pCreateID Mii create ID
     */
    void getCreateID(RFLCreateID* pCreateID) const;
    /**
     * @brief Set this player's Mii create ID
     *
     * @param pCreateID Mii create ID
     */
    void setCreateID(const RFLCreateID* pCreateID);

    /**
     * @brief Gets the time this player was registered with the player list
     */
    RPTime32 getDebutTime() const;
    /**
     * @brief Sets the time this player was registered with the player list
     *
     * @param time Debut time
     */
    void setDebutTime(RPTime32 time);
    /**@}*/

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
     * @brief Player data flags
     */
    enum {
        EFlag_Registered = 1, //!< Registered with the player list
        EFlag_FirstPlay = 2, //!< Completed one minigame
    };

private:
    //! Player data flags
    EGG::TBitFlag<u32> mPlayerFlags; // at 0x0
    //! Mii create/unique ID
    RFLCreateID mCreateID; // at 0x4
    //! Time the player was registered
    RPTime32 mDebutTime; // at 0xC

    //! My Record leaderboard for each game
    s32 mMyRecords[EGame_Max][MY_RECORDS_LENGTH]; // at 0x10
    //! Medal earned in each game
    u8 mMedals[EGame_Max]; // at 0xC4
    //! Medal cutscene flags
    EGG::TBitFlag<u8> mMedalDemoFlags; // at 0xCD
};

//! @}

#endif
