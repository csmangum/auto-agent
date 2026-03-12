import { useRoleSimulation } from '../context/RoleSimulationContext';
import CustomerPortal from './simulation/CustomerPortal';
import RepairShopPortal from './simulation/RepairShopPortal';
import ThirdPartyPortal from './simulation/ThirdPartyPortal';
import RoleSelectLanding from './simulation/RoleSelectLanding';

export default function Simulation() {
  const { role } = useRoleSimulation();

  switch (role) {
    case 'customer':
      return <CustomerPortal />;
    case 'repair_shop':
      return <RepairShopPortal />;
    case 'third_party':
      return <ThirdPartyPortal />;
    default:
      return <RoleSelectLanding />;
  }
}
