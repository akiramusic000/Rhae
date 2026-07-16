#include <nw4r/ef.h>

namespace nw4r {
namespace ef {

void createChild(u8 *pCmdList, u16 param_2, AnimCurveHeader *,
                 AnimCurveNameTable *, AnimCurveRandomTable *, Particle *,
                 u32) {
  if (pCmdList[2] == 0) {
    param_2 = (u16)(pCmdList + 0xC);
  } else {
  }
}

} // namespace ef
} // namespace nw4r
