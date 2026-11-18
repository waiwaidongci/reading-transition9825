export const roles={admin:'负责人',analyst:'分析师',viewer:'业务阅读者'};
export const runStates={queued:'队列中',running:'正在计算',completed:'已完成',failed:'失败'};
export const arrivalStates={queued:'排队等待',running:'分批求解中',completed:'已收敛',failed:'未收敛/失败'};
export const reviewStates={draft:'待复核',approved:'已批准'};
export const arrivalClassLabels={
  target:'目标章',
  reachable:'可到达目标',
  unreachable_cycle:'无路可达·循环分量',
  unreachable_exit:'无路可达·会话退出'
};
