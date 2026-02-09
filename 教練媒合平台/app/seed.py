from .database import engine, SessionLocal
from .models import Base, User, CoachProfile, Review, Booking, Event, CoachSubscription
from .auth import get_password_hash
import json
import random
from datetime import datetime, timedelta

def seed_data():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 1. 建立管理員
    admin = User(
        email="admin@taichung.com",
        hashed_password=get_password_hash("admin123"),
        role="admin"
    )
    db.add(admin)
    db.flush()

    # Create fake students for reviews
    student_users = []
    student_names = ['小明', '小華', '大壯', '雅婷', '欣怡', '美玲', '志明', '春嬌']
    for i in range(10):
        s_user = User(
            email=f"student_{i}@example.com",
            hashed_password=get_password_hash("password123"),
            role="student",
            name=f"學員 {random.choice(student_names)}"
        )
        db.add(s_user)
        student_users.append(s_user)
    db.flush()

    # Review templates pool
    review_templates = {
        "健身": [
            "教練非常專業，細心糾正我的深蹲動作，獲益良多！",
            "人很有耐心，教學風格很幽默，讓重訓不再枯燥。",
            "這是我遇過最專業的健身教練，推薦給想認真增肌的人。",
            "環境很好，教練給的飲食建議也非常實用。",
            "很有系統的教學，循序漸進讓我進步神速。"
        ],
        "潛水": [
            "教練帶得非常安心，水下攝影技術也超強，照片超美！",
            "第一次體驗潛水，教練在水下一直關注我的狀態，很有安全感。",
            "課程解說很詳盡，成功拿到OW證照了，感動！",
            "耗氣控制教得很好，這次潛水時間比以前長很多。",
            "中性浮力練很久都練不好，教練一下就點出關鍵，推薦！"
        ],
        "滑雪": [
            "滑雪初學者的救星！教練教的剎車技巧超級管用。",
            "教練滑雪超帥，影片回放分析非常精準。",
            "雖然一直摔倒，但教練很有耐心鼓勵我，終於學會轉彎了。",
            "教學很有條理，讓我們在短時間內就掌握了基本技巧。",
            "專業滑雪指導，裝備檢查也很仔細，安全第一。"
        ]
    }

    # 2. 建立 20 位示範教練
    coaches_data = [
        {
            "email": "fitness_chen@example.com",
            "name": "陳大威 (David)",
            "sports": ["健身"],
            "regions": ["台中市:西屯區", "台中市:南屯區"],
            "bio": "10年連鎖健身房經驗，專攻增肌減脂與體態雕塑。曾在健美比賽獲得前三名，致力於幫新手建立信心。",
            "sub": "elite",
            "price": "1500-2200",
            "style": ["鼓勵型", "專業嚴謹"],
            "tags": ["專業教練", "健美冠軍", "增肌專長"],
            "spec": ["增肌", "減脂", "體態雕塑", "動作與姿勢調整"],
            "verified": True
        },
        {
            "email": "dive_lin@example.com",
            "name": "林巧巧 (Chloe)",
            "sports": ["潛水"],
            "regions": ["台中市:西屯區", "台中市:北區"],
            "bio": "PADI 開放水域教練，喜歡台中的生活環境。潛水不僅是運動，更是對大自然的敬畏。",
            "sub": "pro",
            "price": "3000-8000",
            "style": ["耐心", "安全至上"],
            "tags": ["PADI認證", "耐心教學", "推薦"],
            "spec": ["體驗/初學", "OW/AOW", "中性浮力"],
            "verified": True
        },
        {
            "email": "ski_wang@example.com",
            "name": "王阿奇 (Archie)",
            "sports": ["滑雪"],
            "regions": ["台中市:南屯區", "台中市:大里區"],
            "bio": "滑雪愛好者，每年寒假固定在國外教學。提供室內模擬機教學，讓你在台灣就練好基本功。",
            "sub": "free",
            "price": "2000-4500",
            "style": ["高效率", "有趣"],
            "tags": ["室內滑雪", "新手友善"],
            "spec": ["新手入門", "建立信心（怕摔）"],
            "gear": "Ski",
            "verified": False
        },
        {
            "email": "power_lift@example.com",
            "name": "巨力山姆 (Sam)",
            "sports": ["健身"],
            "regions": ["台中市:西區", "台北市:信義區"],
            "bio": "力量舉專長，致力於幫助學員突破力量天花板。",
            "sub": "elite",
            "price": "1800-2600",
            "style": ["專業嚴謹", "系統化/有計畫"],
            "tags": ["力量舉", "SBD專精"],
            "spec": ["增肌", "體能/耐力", "動作與姿勢調整"],
            "verified": True
        },
        {
            "email": "aqua_bella@example.com",
            "name": "水樣貝拉",
            "sports": ["潛水"],
            "regions": ["台中市:西屯區", "高雄市:左營區"],
            "bio": "熱愛海洋，希望能帶領更多人看見台灣水底的美。",
            "sub": "pro",
            "price": "3500-7000",
            "style": ["耐心陪跑/鼓勵型", "安全保守/動作調整型"],
            "tags": ["海洋環保", "女子潛水"],
            "spec": ["體驗/初學", "OW/AOW", "中性浮力", "怕水建立信心"],
            "verified": True
        },
        {
            "email": "snow_pro@example.com",
            "name": "極限雪王 (Leo)",
            "sports": ["滑雪"],
            "regions": ["台中市:南屯區", "新北市:淡水區"],
            "bio": "國際滑雪協會認證，專攻特技滑雪與高難度地形。",
            "sub": "elite",
            "price": "3000-9000",
            "style": ["嚴格高效率", "系統化/有計畫"],
            "tags": ["特技滑雪", "國手背景"],
            "spec": ["轉彎技巧", "刻滑入門", "影片回放教學"],
            "gear": "Ski",
            "verified": True
        }
        # ... Other coaches follow same pattern
    ]

    # Add remaining coaches from previous list to make it 20... (simplified for brevity)
    for i in range(14):
        sport = random.choice(["健身", "潛水", "滑雪"])
        coaches_data.append({
            "email": f"coach_extra_{i}@example.com",
            "name": f"教練_{i}",
            "sports": [sport],
            "regions": ["台中市:西屯區"],
            "bio": f"這是第 {i} 位示範教練的簡介。",
            "sub": random.choice(["free", "pro", "elite"]),
            "price": "1000-2000",
            "style": ["專業嚴謹"],
            "tags": ["推薦"],
            "spec": [],
            "verified": random.choice([True, False])
        })

    for data in coaches_data:
        main_sport = data["sports"][0]
        avatar_map = {
            "健身": "/static/images/fitness_coach.png",
            "潛水": "/static/images/diving_coach.png",
            "滑雪": "/static/images/skiing_coach.png"
        }
        coach_avatar = avatar_map.get(main_sport, "/static/images/fitness_coach.png")

        u = User(
            email=data["email"],
            hashed_password=get_password_hash("password123"),
            role="coach"
        )
        db.add(u)
        db.flush()

        cities = []
        districts = []
        for reg in data["regions"]:
            if ":" in reg:
                city, dist = reg.split(":")
                if city not in cities: cities.append(city)
                districts.append(reg)
            else:
                if "台中市" not in cities: cities.append("台中市")
                districts.append(f"台中市:{reg}")

        cp = CoachProfile(
            user_id=u.id,
            display_name=data["name"],
            avatar=coach_avatar,
            bio=data["bio"],
            sports=json.dumps(data["sports"], ensure_ascii=False),
            venues=json.dumps(["1對1", "小班"], ensure_ascii=False),
            service_cities=json.dumps(cities, ensure_ascii=False),
            service_districts=json.dumps(districts, ensure_ascii=False),
            service_all_areas=False,
            teaching_styles=json.dumps(data["style"], ensure_ascii=False),
            audiences=json.dumps(["新手友善", "女性友善"], ensure_ascii=False),
            price_min=int(data["price"].split('-')[0]),
            price_max=int(data["price"].split('-')[-1]) if '-' in data["price"] else 3000,
            subscription_level=data["sub"],
            is_verified=data["verified"],
            view_count=random.randint(100, 500),
            lead_count=random.randint(5, 20),
            status="APPROVED", 
            review_status="APPROVED",
            visibility_status="VISIBLE",
            account_status="ACTIVE",
            tags=json.dumps(data.get("tags", ["專業教練", "推薦"]), ensure_ascii=False),
            specialties=json.dumps(data.get("spec", []), ensure_ascii=False),
            gear_type=data.get("gear")
        )
        db.add(cp)
        db.flush()

        db.add(CoachSubscription(
            coach_id=cp.id,
            plan_id=data["sub"],
            is_active=1,
            start_at=datetime.utcnow() - timedelta(days=5),
            end_at=datetime.utcnow() + timedelta(days=25)
        ))

        # Add Random Reviews
        review_count = random.randint(3, 8)
        total_rating = 0
        for _ in range(review_count):
            student = random.choice(student_users)
            rating = random.choice([4.0, 4.5, 5.0, 5.0]) # Bias towards positive
            comment = random.choice(review_templates.get(main_sport, review_templates["健身"]))
            
            db.add(Review(
                coach_id=cp.id,
                student_id=student.id,
                rating=rating,
                comment=comment,
                is_anonymous=random.choice([True, False]),
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 30))
            ))
            total_rating += rating
        
        cp.rating = total_rating / review_count
        cp.rating_count = review_count

        # Add Events
        event_types = ["impression_coach", "favorite_add", "inquiry_create", "booking_create"]
        weights = [200, 50, 20, 10]
        for i, etype in enumerate(event_types):
            count = random.randint(5, weights[i])
            for _ in range(count):
                db.add(Event(
                    event_type=etype, coach_id=cp.id,
                    created_at=datetime.utcnow() - timedelta(days=random.randint(0, 7))
                ))

    db.commit()
    print("Seed data completed! Admin: admin@taichung.com / admin123")
    db.close()

if __name__ == "__main__":
    seed_data()
